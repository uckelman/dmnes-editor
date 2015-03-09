function lowerBound(list, first, last, value) {
  var i, step, count = last - first;

  while (count > 0) {
    step = count >> 1;
    i = first + step;
    if (list[i] < value) {
      first = ++i;
      count -= step + 1;
    }
    else {
      count = step;
    }
  }

  return first;
}

function binarySearch(list, first, last, value) {
  first = lowerBound(list, first, last, value);
  return (first != last && value >= list[first]);
}

function getList(list, url) {
  // try to load list from storage
  var json = sessionStorage.getItem(list.id);
  if (json) {
    slist = JSON.parse(json);
    list.lastmod = slist.lastmod;
    list.data = slist.data;
  }

  // get new list from url
  var http = new XMLHttpRequest;
  http.open('GET', url, false);
  http.setRequestHeader('If-Modified-Since', list.lastmod);
  http.send();

  if (http.status != 304) {
    // clear list on any response except 304 Not Modified
    list.data = [];
  }

  if (http.status == 200) {
    // set new data and update mtime
    list.data = http.responseText.split('\n');
    list.lastmod = http.getResponseHeader('Last-Modified');
    // store the updated list
    sessionStorage.setItem(list.id, JSON.stringify(list));
  }
}

function setDatalist(data, first, last, dlist) {
  // set the new elements
  var frag = document.createDocumentFragment();
  for (var i = first; i < last; ++i) {
    var opt = document.createElement('option');
    opt.setAttribute('value', data[i]);
    frag.appendChild(opt);
  }

  dlist.appendChild(frag);
}

function nextPrefix(p) {
  return p.substring(0, p.length-1) +
    String.fromCodePoint(p[p.length-1].charCodeAt()+1);
}

function updateDatalist(data, input) {
  var l, h;

  if (input.value) {
    l = lowerBound(data, 0, data.length, input.value);
    h = lowerBound(data, l, data.length, nextPrefix(input.value));
  }
  else {
    l = 0;
    h = data.length;
  }

  var dlist = input.list;
  var dlist_id = dlist.id;
  var dlist_par = dlist.parentNode;
  dlist_par.removeChild(dlist);
  input.setAttribute('list', null);

  dlist = document.createElement('datalist');
  dlist.id = dlist_id;
  setDatalist(data, l, h, dlist);

  dlist_par.appendChild(dlist);
  input.setAttribute('list', dlist_id);
}

function updateBibKeys(input) {
  updateDatalist(bibkeys.data, input);
}

function validateBibKey(input) {
  var result = input.value ?
    binarySearch(bibkeys.data, 0, bibkeys.data.length, input.value) : false;
  input.setCustomValidity(result ? '' : 'Unknown bib key.');
  return result;
}

function updateNyms(input) {
  updateDatalist(nyms.data, input);
}

function validateNym(input) {
  var result = input.value ?
    binarySearch(nyms.data, 0, nyms.data.length, input.value) : true;
  input.setCustomValidity(result ? '' : 'Unknown nym.');
  return result;
}

function addNymInput(button) {
  this.max_nym = ++this.max_nym || 1; // first additional nym is 1
  var copy_nym_id = 'nym_' + this.max_nym;

  // make new nym input
  var orig_nym = document.getElementById('nym_0');
  var copy_nym = orig_nym.cloneNode(false);
  copy_nym.setAttribute('id', copy_nym_id);
  copy_nym.value = '';

  // make new datalist
  var dlist = document.createElement('datalist');
  dlist.setAttribute('id', copy_nym_id + '_list');
  copy_nym.setAttribute('list', copy_nym_id + '_list');

  var td = document.createElement('td');
  td.appendChild(copy_nym);
  td.appendChild(dlist);

  // move the button down a row
  var bi_row = button.parentNode.parentNode;
  button.parentNode.removeChild(button);
  td.appendChild(button);

  var tr = document.createElement('tr');
  tr.appendChild(document.createElement('td'));
  tr.appendChild(td);

  bi_row.parentNode.insertBefore(tr, bi_row.nextElementSibling);
}

function validateVNF() {
  var key = document.getElementById('key');
  var result = validateBibKey(key);

  var nyms = document.getElementsByName("nym");
  for (var input of nyms) {
    result &= validateNym(input);
  }

  // We must actually return true or false for onsubmit,
  // not just something coercible. Strange but true.
  return result == true;
}
