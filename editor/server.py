#!/usr/bin/python3 -b

import os
#import subprocess
import subprocess32 # use until we move to Python 3
import traceback
import unicodedata

import werkzeug.security

import flask
from flask import abort, flash, g, redirect, render_template, request, session, url_for

import lxml
from lxml.builder import E

app = flask.Flask(__name__)
app.config.from_object(__name__)

app.config.update(dict(
  REPO_URL='git@github.com:uckelman/test.git',
  CNF_DIR='CNFs',
  VNF_DIR='VNFs',
  CNF_SCHEMA='schemata/cnf.xsd',
  VNF_SCHEMA='schemata/vnf.xsd',
  SECRET_KEY=os.urandom(128),
  DEBUG=False
))

# password hash generated by:
#
#   werkzeug.security.generate_password_hash('password')
#

#
# User accounts
#

class User(object):
  def __init__(self, username, pwhash, realname, email):
    self.username = username
    self.pwhash = pwhash
    self.realname = realname
    self.email = email

  def check_password(self, password):
    return werkzeug.security.check_password_hash(self.pwhash, password)


accounts = {
  'liana': User(
    'liana',  # yoIN3i)2k
    'pbkdf2:sha1:1000$N64I7Fg1$5ed44d1125456db5a6ab8a36f88f0577a9f91e13',
    'Sara L. Uckelman',
    'liana@ellipsis.cx'
  ),
  'uckelman': User(
    'uckelman',
    'pbkdf2:sha1:1000$fPQl6n0t$3988730ff8770775e31ca325758b5e059684ca4b',
    'Joel Uckelman',
    'uckelman@nomic.net'
  ),
}


#
# XML schemas
#

def load_schema(filename):
  with open(filename) as f:
    doc = lxml.etree.parse(f)

  return lxml.etree.XMLSchema(doc)


def get_cnf_schema():
  if not hasattr(g, 'cnf_schema'):
    g.cnf_schema = load_schema(app.config['CNF_SCHEMA'])
  return g.cnf_schema


def get_vnf_schema():
  if not hasattr(g, 'vnf_schema'):
    g.vnf_schema = load_schema(app.config['VNF_SCHEMA'])
  return g.vnf_schema


#
# Git functions
#

class SubprocessError(subprocess32.CalledProcessError):
  def __init__(self, **kwargs):
    super(SubprocessError, self).__init__(**kwargs)


  def __str__(self):
    indent = '  '
    return '{}\n\nOutput:\n{}{}'.format(
      super(SubprocessError, self).__str__(),
      indent,
      ('\n' + indent).join(self.output.splitlines())
    )


def do_git(repo_dir, cmd, *args):
  cmdline = ['git', cmd] + list(args)
  with subprocess32.Popen(
    cmdline, cwd=repo_dir,
    stdout=subprocess32.PIPE,
    stderr=subprocess32.STDOUT
  ) as proc:
    out = proc.communicate(timeout=10)[0]
    if proc.returncode:
      raise SubprocessError(
        returncode=proc.returncode,
        cmd=cmdline,
        output=out
      )

  flash('% {}\n{}'.format(' '.join(cmdline), out), 'git')


def git_clone(base_dir, repo_url, repo_dir):
  do_git(base_dir, 'clone', repo_url, repo_dir)


def git_config(repo_dir, *args):
  do_git(repo_dir, 'config', *args)


def git_config_user(repo_dir, name, email):
  do_git(repo_dir, 'config', 'user.name', name)
  do_git(repo_dir, 'config', 'user.email', email)


#def git_clone_branch(base_dir, repo_url, repo_dir, branch):
#  do_git(base_dir, 'clone', '-b', branch, '--single-branch', repo_url, repo_dir)


def git_checkout_branch(repo_dir, branch):
  do_git(repo_dir, 'checkout', '-B', branch)


def git_add_file(repo_dir, path):
  do_git(repo_dir, 'add', path)


def git_commit_file(repo_dir, author, msg, path):
  do_git(repo_dir, 'commit', '--author', author, '-m', msg, path)


def git_pull(repo_dir, repo, refspec):
  do_git(repo_dir, 'pull', repo, refspec)


def git_push(repo_dir, repo, refspec):
  do_git(repo_dir, 'push', repo, refspec)


#
#
#

def prefix_branch(s, maxlen=3):
  return [s[n-1:n] for n in range(1,maxlen+1)] + [s]


def build_path(basedir, base):
  base = unicodedata.normalize('NFKC', unicode(base).lower())
  for evil in os.pardir, os.sep, os.altsep:
    if evil and evil in base:
      raise RuntimeError('Evil path: ' + base)
  return os.path.join(basedir, *prefix_branch(base)) + '.xml'


def cnf_path(cnf):
  return build_path(app.config['CNF_DIR'], cnf['nym'])


def vnf_path(vnf):
  return build_path(
    app.config['VNF_DIR'],
    '{}_{}_{}'.format(vnf['name'], vnf['date'], vnf['bib_key'])
  )


def xmlfrag(key, obj):
  return lxml.etree.fromstring('<{0}>{1}</{0}>'.format(key, obj[key]))


def cnf_build(cnf, schema):
  root = E.cnf(
    E.nym(cnf['nym']),
    E.gen(cnf['gen']),
    xmlfrag('etym', cnf),
    xmlfrag('def', cnf),
    xmlfrag('usg', cnf),
    xmlfrag('note', cnf)
  ) 

  schema.assertValid(root)
  return lxml.etree.ElementTree(root)


def vnf_build(vnf, schema):
  root = E.vnf(
    E.name(vnf['name']),
    E.nym(vnf['nym']),
    E.gen(vnf['gen']),
    E.case(vnf['case']),
    E.lang(vnf['lang']),
    xmlfrag('place', vnf),
    E.date(vnf['date']),
    E.bibl(
      E.key(vnf['bib_key']),
      E.loc(vnf['bib_loc'])
    ),
    xmlfrag('note', vnf)
  ) 

  schema.assertValid(root)
  return lxml.etree.ElementTree(root)


def write_tree(tree, path):
  try:
    os.makedirs(os.path.dirname(path))
  except os.error:
    pass
# Python 3:
#  os.makedirs(os.path.dirname(path), exist_ok=True)
  with open(path, 'wb') as f:
    tree.write(
      f,
      xml_declaration='<?xml version="1.0" encoding="UTF-8"?>',
      encoding='UTF-8',
      pretty_print=True
    )


def prepare_git(username):
  upath = os.path.join('users', username)
  repo_exists = os.path.isdir(upath)

  if not repo_exists:
    # set up local repo
    git_clone('users', app.config['REPO_URL'], username)
    user = accounts[username]
    git_config_user(upath, user.realname, user.email)
    git_config(upath, 'push.default', 'simple')

  git_checkout_branch(upath, username)

  if repo_exists:
    # ensure existing repo is current
    git_pull(upath, 'origin', username)
    git_pull(upath, 'origin', 'master')
 

def commit_to_git(username, path, tree):
  upath = os.path.join('users', username)
  write_tree(tree, os.path.join(upath, path))
  git_add_file(upath, path)
  user = accounts[username]
  author = '{} <{}>'.format(user.realname, user.email)
  msg = 'Added ' + path
  git_commit_file(upath, author, msg, path)


def push_back_to_git(username):
  upath = os.path.join('users', username)
  git_push(upath, 'origin', username + ':' + username) 


# TODO: handle exceptions

#
# User authentication
#

def auth_user(username, password):
  user = accounts.get(username, None)
  if user:
    if user.check_password(password):
      return None
  return 'Invalid username or password!'


#
#
#

def request_size(req):
  return sum(len(v) for v in req.values())


#
# URL handlers
#

@app.route('/')
def slash():
  return 'Welcome to the DMNES!'


@app.route('/login', methods=['GET', 'POST'])
def login():
  error = None
  if request.method == 'POST':
    username = request.form['username']
    password = request.form['password']
    error = auth_user(username, password)
    if error == None:
      session['username'] = username
      prepare_git(username)
      flash('Welcome, ' + username + '.')
      return redirect(url_for('cnf'))

  return render_template('login.html', error=error)


@app.route('/logout')
def logout():
  username = session.pop('username', None)
  if username:
    push_back_to_git(username)
    flash('Goodbye, ' + username + '.')
  return redirect(url_for('login'))


class FormStruct:
  def __init__(self, path_func, schema, build_func, cn_func, keepers, templ):
    self.path_func = path_func
    self.schema = schema
    self.build_func = build_func
    self.cn_func = cn_func
    self.keepers = keepers
    self.templ = templ


CNF = FormStruct(
  cnf_path,
  load_schema(app.config['CNF_SCHEMA']),
  cnf_build,
  lambda x: x['nym'],
  (),
  'cnf.html'
)

VNF = FormStruct(
  vnf_path,
  load_schema(app.config['VNF_SCHEMA']),
  vnf_build,
  lambda x: x['name'],
  ('lang', 'place', 'date', 'bib_key'),
  'vnf.html'
)


def handle_entry_form(fstruct):
  if 'username' not in session:
    abort(401)

  vals = {}

  if request.method == 'POST':
    if request_size(request.form) > 2048:
      abort(413)

    username = session['username']
    localpath = fstruct.path_func(request.form)
    fullpath = os.path.join('users', username, localpath)

    # don't clobber existing entries
    if os.path.exists(fullpath):
      abort(409)

    # write the entry and report that
    tree = fstruct.build_func(request.form, fstruct.schema)
    commit_to_git(username, localpath, tree)

    flash('Added ' + fstruct.cn_func(request.form))

    # retain some input values for next entry 
    vals = {k: request.form[k] for k in fstruct.keepers}

  return render_template(fstruct.templ, vals=vals)


@app.route('/cnf', methods=['GET', 'POST'])
def cnf():
  return handle_entry_form(CNF)


@app.route('/vnf', methods=['GET', 'POST'])
def vnf():
  return handle_entry_form(VNF)


@app.errorhandler(Exception)
def handle_exception(ex):
  ex_text = traceback.format_exc()
  return render_template('exception.html', ex=ex_text), 500


if __name__ == '__main__':
  app.run()