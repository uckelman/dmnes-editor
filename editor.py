#!/usr/bin/python3 -b

import datetime
import itertools
import os
import subprocess
import traceback
import unicodedata

import werkzeug.datastructures

from flask import Flask, Response, abort, flash, render_template, request, session

import lxml
from lxml.builder import E

from auth import User, handle_login, handle_logout, login_required


def default_config():
  # locally scope these
  base_dir = os.path.dirname(os.path.realpath(__file__))
  users_dir = os.path.join(base_dir, 'users')
  schema_dir = os.path.join(base_dir, 'schemata')

  return dict(
    BASE_DIR=base_dir,
    USERS_DIR=users_dir,
    SCHEMA_DIR=schema_dir,
    CNF_DIR='CNFs',
    VNF_DIR='VNFs',
    BIB_DIR='bib',
    CNF_SCHEMA=os.path.join(schema_dir, 'cnf.xsd'),
    VNF_SCHEMA=os.path.join(schema_dir, 'vnf.xsd'),
    SECRET_KEY=os.urandom(128),
    DEBUG=False
  )


app = Flask(__name__)
app.config.update(default_config())
app.config.from_pyfile('config.py')
app.config['USERS'] = { x[0]: User(*x) for x in app.config['USERS'] }


#
# XML schemata
#

def load_schema(filename):
  with open(filename) as f:
    doc = lxml.etree.parse(f)
  return lxml.etree.XMLSchema(doc)


#
# Shell out
#

class SubprocessError(subprocess.CalledProcessError):
  def __init__(self, **kwargs):
    super(SubprocessError, self).__init__(**kwargs)


  def __str__(self):
    indent = '  '
    return '{}\n\nOutput:\n{}{}'.format(
      super(SubprocessError, self).__str__(),
      indent,
      ('\n' + indent).join(self.output.splitlines())
    )


def do_cmd(cwd, *args):
  with subprocess.Popen(
    (a.encode('utf-8') for a in args),
    cwd=cwd,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT
  ) as proc:
    out = proc.communicate(timeout=60)[0].decode('utf-8')
    if proc.returncode:
      raise SubprocessError(
        returncode=proc.returncode,
        cmd=args,
        output=out
      )

  return '% {}\n{}'.format(' '.join(args), out)


# FIXME: need to catch TimeoutExpired
def do_cmd_out(cwd, ok, *args):
  with subprocess.Popen(
    (a.encode('utf-8') for a in args),
    cwd=cwd,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE
  ) as proc:
    out, err = (x.decode('utf-8') for x in proc.communicate(timeout=30))
    if not ok(proc.returncode):
      raise SubprocessError(
        returncode=proc.returncode,
        cmd=args,
        output=out + '\n' + err
      )

  return out


def do_grep(cwd, opts, pat, *paths):
  res = do_cmd_out(cwd, lambda x: x < 2, 'grep', opts, pat, *paths)
  lines = res.splitlines()
  lines.sort()
  return lines


#
# Lookup
#

def get_bibkeys(repo_dir):
  bib_dir = app.config['BIB_DIR']
  return do_grep(repo_dir, '-hoPr', '^\\s*<key>\\K[^<]+', bib_dir)


def get_nyms(repo_dir):
  cnf_dir = app.config['CNF_DIR']
  return do_grep(repo_dir, '-hoPr', '^\\s*<nym>\\K[^<]+', cnf_dir)


#
# Git functions
#

def do_git(repo_dir, cmd, *args):
  out = do_cmd(repo_dir, 'git', cmd, *args)
  flash(out, 'git')


def git_clone(base_dir, repo_url, repo_dir):
  do_git(base_dir, 'clone', repo_url, repo_dir)


def git_config(repo_dir, *args):
  do_git(repo_dir, 'config', *args)


def git_config_user(repo_dir, name, email):
  do_git(repo_dir, 'config', 'user.name', name)
  do_git(repo_dir, 'config', 'user.email', email)


#def git_clone_branch(base_dir, repo_url, repo_dir, branch):
#  do_git(base_dir, 'clone', '-b', branch, '--single-branch', repo_url, repo_dir)

def git_create_branch(repo_dir, branch):
  do_git(repo_dir, 'checkout', '-b', branch)


def git_checkout_branch(repo_dir, branch):
  do_git(repo_dir, 'checkout', branch)


def git_add_file(repo_dir, path):
  do_git(repo_dir, 'add', path)


def git_commit_file(repo_dir, author, msg, path):
  do_git(repo_dir, 'commit', '--author', author, '-m', msg, path)


def git_pull(repo_dir, repo, refspec):
  do_git(repo_dir, 'pull', repo, refspec)


def git_push(repo_dir, repo, refspec):
  do_git(repo_dir, 'push', repo, refspec)


#
# Record construction
#

def prefix_base(s, maxlen):
  l = min(maxlen, len(s))
  return os.path.join(*s[:l]) if l else ''


def sanitize_filename(filename):
  filename = unicodedata.normalize('NFKC', filename.lower())
  if len(filename) > 255:
    raise RuntimeError('Evil path: ' + filename)
  for evil in os.pardir, os.sep, os.altsep:
    if evil and evil in filename:
      raise RuntimeError('Evil path: ' + filename)
  return filename


def build_prefix_base(basedir, basename, depth):
  basename = sanitize_filename(basename)
  return os.path.join(basedir, prefix_base(basename, depth))


def build_prefix_path(basedir, basename, depth):
  basename = sanitize_filename(basename)
  return os.path.join(basedir, prefix_base(basename, depth), basename + '.xml')


def cnf_path(cnf, depth):
  return build_prefix_path(app.config['CNF_DIR'], cnf['nym'], depth)


def vnf_path(vnf, depth):
  return build_prefix_path(
    app.config['VNF_DIR'],
    '{}_{}_{}'.format(
      vnf['name'],
      vnf['date'].replace('/','s'), # slashes are evil, use 's'
      vnf['key']
    ),
    depth
  )


def bib_path(bib, depth):
  return os.path.join(
    app.config['BIB_DIR'],
    sanitize_filename(bib['key']) + '.xml'
  )


def element(key, obj):
  try:
    return E(key, obj[key])
  except KeyError:
    return ''


def element_raw_inner(key, obj, skip_empty=True):
  try:
    val = obj[key]
  except KeyError:
    val = ''

  if skip_empty and not val:
    return ''

  return lxml.etree.fromstring('<{0}>{1}</{0}>'.format(key, val))


def indent(node, depth):
  node.text = '\n' + '  '*(depth+1)
  for e in node[:-1]:
    e.tail = '\n' + '  '*(depth+1)
  node[-1].tail = '\n' + '  '*depth


def cnf_build(cnf, schema):
  root = E.cnf(
    element_raw_inner('nym', cnf),
    E.meta(
      E.live('false')
    ),
    element('gen', cnf),
    element_raw_inner('etym', cnf, skip_empty=False),
    element_raw_inner('usg', cnf),
    element_raw_inner('def', cnf),
    element_raw_inner('lit', cnf),
    element_raw_inner('note', cnf)
  )

  indent(root, 0)
  indent(root.find('meta'), 1)

  schema.assertValid(root)
  return lxml.etree.ElementTree(root)


def vnf_build(vnf, schema):
  # this is odd because we don't know how many nyms there will be
  root = E.vnf(*tuple(itertools.chain(
    (
      element_raw_inner('name', vnf),
      E.meta(
        E.live('false')
      )
    ),
    (
      lxml.etree.fromstring('<nym>{}</nym>'.format(v))
        for v in vnf.getlist('nym') if v
    ),
    (
      element('gen', vnf),
      element('case', vnf),
      E.dim('true' if 'dim' in vnf and vnf['dim'] == 'on' else 'false'),
      element_raw_inner('lang', vnf),
      element_raw_inner('place', vnf),
      element_raw_inner('date', vnf),
      E.bibl(
        element('key', vnf),
        element_raw_inner('loc', vnf)
      ),
      element_raw_inner('note', vnf)
    )
  )))

  indent(root, 0)
  indent(root.find('meta'), 1)
  indent(root.find('bibl'), 1)

  schema.assertValid(root)
  return lxml.etree.ElementTree(root)


def bib_build(bib, schema):
  root = E.bibl(
    element('key', bib),
    lxml.etree.fromstring(bib['entry'])
  )

  indent(root, 0)
  indent(root[1], 1)

  return lxml.etree.ElementTree(root)


def write_tree(tree, path):
  path = path.encode('utf-8')
  os.makedirs(os.path.dirname(path), exist_ok=True)
  with open(path, 'wb') as f:
    tree.write(
      f,
      xml_declaration=True,
      encoding='utf-8',
      pretty_print=False
    )


def repo_for(username):
  return os.path.join(app.config['USERS_DIR'], username)


def prepare_git(username):
  upath = repo_for(username)
  repo_exists = os.path.isdir(upath.encode('utf-8'))

  if not repo_exists:
    # set up local repo
    git_clone(app.config['USERS_DIR'], app.config['REPO_URL'], username)
    user = app.config['USERS'][username]
    git_config_user(upath, user.realname, user.email)
    git_config(upath, 'push.default', 'simple')
    git_create_branch(upath, username)
    git_push(upath, 'origin', username + ':' + username)
  else:
    # ensure existing repo is current
    git_checkout_branch(upath, username)
    git_pull(upath, 'origin', username)
    git_pull(upath, 'origin', 'master')


def commit_to_git(username, path, tree):
  upath = repo_for(username)
  write_tree(tree, os.path.join(upath, path))
  git_add_file(upath, path)
  user = app.config['USERS'][username]
  author = '{} <{}>'.format(user.realname, user.email)
  msg = 'Added ' + path
  git_commit_file(upath, author, msg, path)


def push_back_to_git(username):
  upath = repo_for(username)
  git_push(upath, 'origin', username + ':' + username)


#
# URL handlers
#

@app.route('/')
@login_required
def slash():
  return 'Welcome to the DMNES!'


def login_setup(username):
  prepare_git(username)
  session['cnf'] = session['vnf'] = session['bib'] \
                                  = datetime.datetime.utcnow()

@app.route('/login', methods=['GET', 'POST'])
def login():
  return handle_login(login_setup, 'vnf')


def logout_teardown(username):
  push_back_to_git(username)


@app.route('/logout')
@login_required
def logout():
  return handle_logout(logout_teardown)


RFC1123 = '%a, %d %b %Y %H:%M:%S GMT'


def conditional_response(key, func, username):
  mtime_local = session[key]

  try:
    ims = request.headers['If-Modified-Since']
    mtime_remote = datetime.datetime.strptime(ims, RFC1123)
  except (KeyError, ValueError):
    mtime_remote = datetime.datetime(datetime.MINYEAR, 1, 1)

  if mtime_local > mtime_remote:
    lines = func(repo_for(username))
    response = Response('\n'.join(lines), mimetype='text/plain')
    response.headers.add('Last-Modified', mtime_local.strftime(RFC1123))
  else:
    response = Response(status=304)

  return response


@app.route('/bibkeys', methods=['GET'])
@login_required
def bibkeys():
  username = session['username']
  return conditional_response('bib', get_bibkeys, username)


@app.route('/nyms', methods=['GET'])
@login_required
def nyms():
  username = session['username']
  return conditional_response('cnf', get_nyms, username)


class FormStruct:
  def __init__(self, path_func, prefix_depth, schema, build_func, cn_func, keepers, templ):
    self.path_func = path_func
    self.prefix_depth = prefix_depth
    self.schema = schema
    self.build_func = build_func
    self.cn_func = cn_func
    self.keepers = keepers
    self.templ = templ


CNF = FormStruct(
  cnf_path,
  3,
  load_schema(app.config['CNF_SCHEMA']),
  cnf_build,
  lambda x: x['nym'],
  (),
  'cnf.html'
)

VNF = FormStruct(
  vnf_path,
  6,
  load_schema(app.config['VNF_SCHEMA']),
  vnf_build,
  lambda x: x['name'],
  ('lang', 'place', 'date', 'key'),
  'vnf.html'
)

BIB = FormStruct(
  bib_path,
  0,
#  load_schema(app.config['BIB_SCHEMA']),
  None,
  bib_build,
  lambda x: x['key'],
  (),
  'bib.html'
)


class FormError(Exception):
  def __init__(self, message):
    super(FormError, self).__init__()
    self.message = message


def request_size(req):
  return sum(len(v) for v in req.values())


def handle_entry_form(fstruct):
  vals = None

  if request.method == 'POST':
    try:
      if request_size(request.form) > 2048:
        abort(413)

      # strip leading and trailing whitespace from form input
      form = werkzeug.datastructures.MultiDict([
        (k, v.strip()) for (k, v) in request.form.items()
      ])

      username = session['username']
      localpath = fstruct.path_func(form, fstruct.prefix_depth)
      fullpath = os.path.join(repo_for(username), localpath)

      # don't clobber existing entries
      if os.path.exists(fullpath.encode('utf-8')):
        raise FormError(fullpath + ' already exists')

      # validate the entry
      try:
        tree = fstruct.build_func(form, fstruct.schema)
# FIXME: these are not particularly helpful error messages
# It would be better to highlight the offending field
      except (lxml.etree.DocumentInvalid, lxml.etree.XMLSyntaxError) as e:
        raise FormError(str(e))

      # write the entry and report that
      commit_to_git(username, localpath, tree)
      session[request.endpoint] = datetime.datetime.utcnow()
      flash('Added ' + fstruct.cn_func(form), 'notice')

      # retain some input values for next entry
      vals = werkzeug.datastructures.MultiDict([
        (k, v) for (k, v) in form.items() if k in fstruct.keepers
      ])

    except FormError as e:
      flash(e.message, 'error')
      # retain all input values on error
      vals = form

  return render_template(fstruct.templ, vals=vals)


@app.route('/cnf', methods=['GET', 'POST'])
@login_required
def cnf():
  return handle_entry_form(CNF)


@app.route('/vnf', methods=['GET', 'POST'])
@login_required
def vnf():
  return handle_entry_form(VNF)


@app.route('/bib', methods=['GET', 'POST'])
@login_required
def bib():
  return handle_entry_form(BIB)


@app.errorhandler(Exception)
def handle_exception(ex):
  ex_text = traceback.format_exc()
  return render_template('exception.html', ex=ex_text), 500


if __name__ == '__main__':
  app.run()
