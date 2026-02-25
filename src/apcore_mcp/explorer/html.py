"""Self-contained HTML page for the MCP Tool Explorer."""

_EXPLORER_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MCP Tool Explorer</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, monospace;
         background: #f5f5f5; color: #333; padding: 24px; }
  h1 { font-size: 1.4rem; margin-bottom: 16px; }
  .tool-list { list-style: none; }
  .tool-item { background: #fff; border: 1px solid #ddd; border-radius: 6px;
               padding: 12px 16px; margin-bottom: 8px; cursor: pointer; }
  .tool-item:hover { border-color: #888; }
  .tool-name { font-weight: 600; }
  .tool-desc { color: #666; font-size: 0.9rem; margin-top: 4px; }
  .hint { display: inline-block; background: #e8e8e8; padding: 2px 8px;
          border-radius: 3px; font-size: 0.75rem; margin-right: 4px; }
  .hint-readonly { background: #d4edda; color: #155724; }
  .hint-destructive { background: #f8d7da; color: #721c24; }
  .hint-idempotent { background: #cce5ff; color: #004085; }
  .detail { background: #fff; border: 1px solid #ddd; border-radius: 6px;
            padding: 16px; margin-top: 16px; display: none; }
  .detail.active { display: block; }
  .detail h2 { font-size: 1.1rem; margin-bottom: 12px; }
  .schema-label { font-weight: 600; margin-top: 12px; display: block; }
  pre { background: #282c34; color: #abb2bf; padding: 12px; border-radius: 4px;
        overflow-x: auto; font-size: 0.85rem; margin-top: 4px; }
  #loading { color: #888; }
  .try-it { margin-top: 16px; border-top: 1px solid #eee; padding-top: 16px; }
  .try-it h3 { font-size: 0.95rem; margin-bottom: 8px; }
  .input-editor { width: 100%; min-height: 120px; font-family: monospace;
                  font-size: 0.85rem; padding: 10px; border: 1px solid #ddd;
                  border-radius: 4px; resize: vertical; background: #fafafa; }
  .execute-btn { margin-top: 8px; padding: 8px 20px; background: #4CAF50; color: #fff;
                 border: none; border-radius: 4px; cursor: pointer; font-size: 0.9rem;
                 font-weight: 600; }
  .execute-btn:hover { background: #45a049; }
  .execute-btn:disabled { background: #ccc; cursor: not-allowed; }
  .result-area { margin-top: 12px; }
  .result-area pre { background: #1a2332; }
  .result-error { color: #f93e3e; }
  .result-success { color: #49cc90; }
  .exec-disabled { color: #888; font-size: 0.85rem; font-style: italic; margin-top: 16px; }
</style>
</head>
<body>
<h1>MCP Tool Explorer</h1>
<div id="loading">Loading tools...</div>
<ul class="tool-list" id="tools"></ul>
<div class="detail" id="detail"></div>
<script>
(function() {
  var base = window.location.pathname.replace(/\\/$/, '');
  var toolsEl = document.getElementById('tools');
  var detailEl = document.getElementById('detail');
  var loadingEl = document.getElementById('loading');
  var executeEnabled = null;

  function esc(s) {
    var d = document.createElement('div');
    d.appendChild(document.createTextNode(s));
    return d.innerHTML;
  }

  function defaultFromSchema(schema) {
    if (!schema || !schema.properties) return {};
    var result = {};
    var props = schema.properties;
    for (var key in props) {
      if (!props.hasOwnProperty(key)) continue;
      var t = props[key].type;
      if (props[key]['default'] !== undefined) {
        result[key] = props[key]['default'];
      } else if (t === 'string') {
        result[key] = '';
      } else if (t === 'number' || t === 'integer') {
        result[key] = 0;
      } else if (t === 'boolean') {
        result[key] = false;
      } else if (t === 'array') {
        result[key] = [];
      } else if (t === 'object') {
        result[key] = {};
      } else {
        result[key] = null;
      }
    }
    return result;
  }

  function hintsHtml(annotations) {
    if (!annotations) return '';
    var parts = [];
    if (annotations.readOnlyHint) parts.push('<span class="hint hint-readonly">readOnly</span>');
    if (annotations.destructiveHint) parts.push('<span class="hint hint-destructive">destructive</span>');
    if (annotations.idempotentHint) parts.push('<span class="hint hint-idempotent">idempotent</span>');
    if (annotations.openWorldHint === false) parts.push('<span class="hint">closedWorld</span>');
    return parts.join('');
  }

  fetch(base + '/tools')
    .then(function(r) { return r.json(); })
    .then(function(tools) {
      loadingEl.style.display = 'none';
      tools.forEach(function(t) {
        var li = document.createElement('li');
        li.className = 'tool-item';
        li.innerHTML =
          '<span class="tool-name">' + esc(t.name) + '</span> ' +
          hintsHtml(t.annotations) +
          '<div class="tool-desc">' + esc(t.description || '') + '</div>';
        li.onclick = function() { loadDetail(t.name); };
        toolsEl.appendChild(li);
      });
      fetch(base + '/tools/__probe__/call', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: '{}'
      }).then(function(r) {
        executeEnabled = r.status !== 403;
      }).catch(function() {});
    })
    .catch(function(e) { loadingEl.textContent = 'Error: ' + e; });

  function loadDetail(name) {
    fetch(base + '/tools/' + encodeURIComponent(name))
      .then(function(r) { return r.json(); })
      .then(function(d) {
        detailEl.className = 'detail active';
        var html =
          '<h2>' + esc(d.name) + '</h2>' +
          '<p>' + esc(d.description || '') + '</p>' +
          '<span class="schema-label">Input Schema</span>' +
          '<pre>' + esc(JSON.stringify(d.inputSchema, null, 2)) + '</pre>';

        if (d.annotations) {
          html += '<span class="schema-label">Annotations</span>' +
            '<pre>' + esc(JSON.stringify(d.annotations, null, 2)) + '</pre>';
        }

        html += '<div class="try-it" id="try-it-section">' +
          '<h3>Try it</h3>' +
          '<textarea class="input-editor" id="input-editor">' +
          esc(JSON.stringify(defaultFromSchema(d.inputSchema), null, 2)) +
          '</textarea>' +
          '<button class="execute-btn" id="execute-btn">Execute</button>' +
          '<div class="result-area" id="result-area"></div>' +
          '</div>';

        detailEl.innerHTML = html;

        document.getElementById('execute-btn').onclick = function() {
          execTool(d.name);
        };

        if (executeEnabled === false) {
          var section = document.getElementById('try-it-section');
          if (section) section.innerHTML =
            '<p class="exec-disabled">' +
            'Tool execution is disabled. ' +
            'Launch with --allow-execute to enable.</p>';
        }
      })
      .catch(function(e) {
        detailEl.className = 'detail active';
        detailEl.innerHTML = '<p class="result-error">Failed to load tool details: ' + esc(e.message) + '</p>';
      });
  }

  function execTool(name) {
    var btn = document.getElementById('execute-btn');
    var editor = document.getElementById('input-editor');
    var resultArea = document.getElementById('result-area');

    var inputText = editor.value.trim();
    var inputs;
    try {
      inputs = inputText ? JSON.parse(inputText) : {};
    } catch (e) {
      resultArea.innerHTML = '<p class="result-error">Invalid JSON: ' + esc(e.message) + '</p>';
      return;
    }

    btn.disabled = true;
    btn.textContent = 'Executing...';
    resultArea.innerHTML = '';

    fetch(base + '/tools/' + encodeURIComponent(name) + '/call', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(inputs)
    })
    .then(function(r) {
      if (r.status === 403) {
        executeEnabled = false;
        var section = document.getElementById('try-it-section');
        if (section) section.innerHTML =
          '<p class="exec-disabled">' +
          'Tool execution is disabled. ' +
          'Launch with --allow-execute to enable.</p>';
        return null;
      }
      return r.json().then(function(data) { return {status: r.status, data: data}; });
    })
    .then(function(result) {
      if (!result) return;
      btn.disabled = false;
      btn.textContent = 'Execute';
      if (result.status >= 400) {
        resultArea.innerHTML = '<span class="schema-label result-error">Error (' + result.status + ')</span>' +
          '<pre>' + esc(JSON.stringify(result.data, null, 2)) + '</pre>';
      } else {
        resultArea.innerHTML = '<span class="schema-label result-success">Result</span>' +
          '<pre>' + esc(JSON.stringify(result.data, null, 2)) + '</pre>';
      }
    })
    .catch(function(e) {
      btn.disabled = false;
      btn.textContent = 'Execute';
      resultArea.innerHTML = '<p class="result-error">Request failed: ' + esc(e.message) + '</p>';
    });
  }
})();
</script>
</body>
</html>
"""
