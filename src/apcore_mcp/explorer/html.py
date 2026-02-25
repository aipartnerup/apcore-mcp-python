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
  .curl-section { margin-top: 14px; }
  .curl-block { background: #282c34; color: #abb2bf; padding: 12px; padding-right: 60px;
                border-radius: 4px; overflow-x: auto; font-size: 0.82rem;
                white-space: pre-wrap; word-break: break-all; position: relative;
                font-family: monospace; margin-top: 4px; }
  .copy-btn { position: absolute; top: 8px; right: 8px; background: #3a3f4b; color: #999;
              border: 1px solid #555; border-radius: 3px; padding: 2px 10px;
              font-size: 0.72rem; cursor: pointer; }
  .copy-btn:hover { background: #4a4f5b; color: #fff; }
  .resp-header { display: flex; align-items: center; gap: 12px; margin-top: 12px; }
  .resp-tabs { display: inline-flex; }
  .resp-tab { padding: 3px 10px; background: #eee; border: 1px solid #ddd;
              cursor: pointer; font-size: 0.75rem; user-select: none; }
  .resp-tab:first-child { border-radius: 3px 0 0 3px; }
  .resp-tab:last-child { border-radius: 0 3px 3px 0; }
  .resp-tab.active { background: #555; color: #fff; border-color: #555; }
  .resp-pane { display: none; }
  .resp-pane.active { display: block; }
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
      if (props[key]['default'] != null) { // != null catches both null and undefined
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

    var bodyStr = JSON.stringify(inputs);
    var callUrl = window.location.origin + base + '/tools/' + encodeURIComponent(name) + '/call';
    var curlBody = bodyStr.replace(/'/g, "'\\\\''" );
    var curlCmd = [
      "curl -X POST '" + callUrl + "' \\\\",
      "  -H 'Content-Type: application/json' \\\\",
      "  -d '" + curlBody + "'"
    ].join("\\n");

    fetch(base + '/tools/' + encodeURIComponent(name) + '/call', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: bodyStr
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
      var data = result.data;
      var html = '';

      html += '<div class="curl-section">' +
        '<span class="schema-label">cURL</span>' +
        '<div class="curl-block"><code class="curl-cmd">' + esc(curlCmd) +
        '</code><button class="copy-btn" id="copy-curl-btn">Copy</button></div></div>';

      if (data.isError) {
        var errText = (data.content || []).map(function(c) { return c.text || ''; }).join('\\n');
        html += '<span class="schema-label result-error">Response &mdash; Error</span>' +
          '<pre>' + esc(errText) + '</pre>';
      } else {
        var texts = (data.content || []).filter(function(c) { return c.type === 'text'; });
        var display = texts.map(function(c) {
          try { return JSON.parse(c.text); } catch(e) { return c.text; }
        });
        var output = display.length === 1 ? display[0] : display;
        var friendlyJson = JSON.stringify(output, null, 2);
        var rawJson = JSON.stringify(data, null, 2);

        html += '<div class="resp-header">' +
          '<span class="schema-label result-success" style="margin:0">Response</span>' +
          '<span class="resp-tabs">' +
          '<span class="resp-tab active" data-tab="friendly">Result</span>' +
          '<span class="resp-tab" data-tab="raw">Raw MCP</span>' +
          '</span></div>' +
          '<pre class="resp-pane active" data-pane="friendly">' + esc(friendlyJson) + '</pre>' +
          '<pre class="resp-pane" data-pane="raw">' + esc(rawJson) + '</pre>';
      }

      resultArea.innerHTML = html;

      var copyBtn = document.getElementById('copy-curl-btn');
      if (copyBtn) {
        copyBtn.onclick = function() {
          var cmd = resultArea.querySelector('.curl-cmd');
          if (cmd && navigator.clipboard) {
            navigator.clipboard.writeText(cmd.textContent).then(function() {
              copyBtn.textContent = 'Copied!';
              setTimeout(function() { copyBtn.textContent = 'Copy'; }, 1500);
            }).catch(function() {
              copyBtn.textContent = 'Failed';
              setTimeout(function() { copyBtn.textContent = 'Copy'; }, 1500);
            });
          }
        };
      }
      var tabs = resultArea.querySelectorAll('.resp-tab');
      for (var i = 0; i < tabs.length; i++) {
        (function(tab) {
          tab.onclick = function() {
            var target = tab.getAttribute('data-tab');
            var allTabs = resultArea.querySelectorAll('.resp-tab');
            var allPanes = resultArea.querySelectorAll('.resp-pane');
            for (var j = 0; j < allTabs.length; j++) {
              allTabs[j].className = allTabs[j].getAttribute('data-tab') === target
                ? 'resp-tab active' : 'resp-tab';
            }
            for (var j = 0; j < allPanes.length; j++) {
              allPanes[j].className = allPanes[j].getAttribute('data-pane') === target
                ? 'resp-pane active' : 'resp-pane';
            }
          };
        })(tabs[i]);
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
