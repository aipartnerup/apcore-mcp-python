"""Self-contained HTML page for the APCore MCP Tool Explorer."""

_EXPLORER_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>APCore MCP Tool Explorer</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, monospace;
         background: #f5f5f5; color: #333; padding: 24px; }
  h1 { font-size: 1.4rem; margin-bottom: 16px; }
  .tool-list { list-style: none; }
  .tool-item { background: #fff; border: 1px solid #ddd; border-radius: 6px;
               margin-bottom: 8px; overflow: hidden; }
  .tool-header { padding: 12px 16px; cursor: pointer; display: flex;
                 align-items: flex-start; gap: 8px; }
  .tool-header:hover { background: #fafafa; }
  .tool-toggle { color: #999; font-size: 0.7rem; margin-top: 3px; transition: transform 0.2s; flex-shrink: 0; }
  .tool-item.expanded .tool-toggle { transform: rotate(90deg); }
  .tool-item.expanded { border-color: #888; }
  .tool-summary { flex: 1; }
  .tool-name { font-weight: 600; }
  .tool-desc { color: #666; font-size: 0.9rem; margin-top: 4px; }
  .hint { display: inline-block; background: #e8e8e8; padding: 2px 8px;
          border-radius: 3px; font-size: 0.75rem; margin-right: 4px; }
  .hint-readonly { background: #d4edda; color: #155724; }
  .hint-destructive { background: #f8d7da; color: #721c24; }
  .hint-idempotent { background: #cce5ff; color: #004085; }
  .tool-detail { display: none; padding: 0 16px 16px; border-top: 1px solid #eee; }
  .tool-item.expanded .tool-detail { display: block; }
  .detail-title { font-size: 1.1rem; margin: 12px 0; }
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
  .auth-bar { display: flex; align-items: center; gap: 8px; margin-bottom: 16px;
              padding: 10px 14px; background: #fff; border: 1px solid #ddd;
              border-radius: 6px; }
  .auth-bar label { font-weight: 600; font-size: 0.85rem; white-space: nowrap; }
  .auth-bar input { flex: 1; font-family: monospace; font-size: 0.82rem;
                     padding: 6px 10px; border: 1px solid #ddd; border-radius: 4px; }
  .auth-bar .auth-status { font-size: 0.75rem; padding: 2px 8px; border-radius: 3px; }
  .auth-bar .auth-locked { background: #d4edda; color: #155724; }
  .auth-bar .auth-unlocked { background: #f8d7da; color: #721c24; }
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
<h1>APCore MCP Tool Explorer</h1>
<div class="auth-bar" id="auth-bar">
  <label for="auth-token">Authorization</label>
  <input type="text" id="auth-token" placeholder="Bearer eyJhbGci...">
  <span class="auth-status auth-unlocked" id="auth-status">No token</span>
</div>
<div id="loading">Loading tools...</div>
<ul class="tool-list" id="tools"></ul>
<script>
(function() {
  var base = window.location.pathname.replace(/\\/$/, '');
  var toolsEl = document.getElementById('tools');
  var loadingEl = document.getElementById('loading');
  var authInput = document.getElementById('auth-token');
  var authStatus = document.getElementById('auth-status');
  var executeEnabled = null;

  function getAuthHeaders() {
    var token = (authInput.value || '').trim();
    if (!token) return {};
    if (token.toLowerCase().indexOf('bearer ') !== 0) token = 'Bearer ' + token;
    return {'Authorization': token};
  }

  function updateAuthStatus() {
    var token = (authInput.value || '').trim();
    if (token) {
      authStatus.textContent = 'Token set';
      authStatus.className = 'auth-status auth-locked';
    } else {
      authStatus.textContent = 'No token';
      authStatus.className = 'auth-status auth-unlocked';
    }
  }
  authInput.addEventListener('input', updateAuthStatus);

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
      if (props[key]['default'] != null) {
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

  fetch(base + '/tools', {headers: getAuthHeaders()})
    .then(function(r) { return r.json(); })
    .then(function(tools) {
      loadingEl.style.display = 'none';
      tools.forEach(function(t) {
        var li = document.createElement('li');
        li.className = 'tool-item';
        li.setAttribute('data-tool', t.name);
        li.innerHTML =
          '<div class="tool-header">' +
            '<span class="tool-toggle">&#9654;</span>' +
            '<div class="tool-summary">' +
              '<span class="tool-name">' + esc(t.name) + '</span> ' +
              hintsHtml(t.annotations) +
              '<div class="tool-desc">' + esc(t.description || '') + '</div>' +
            '</div>' +
          '</div>' +
          '<div class="tool-detail"></div>';
        li.querySelector('.tool-header').onclick = function() { toggleTool(li, t.name); };
        toolsEl.appendChild(li);
      });
      var probeHeaders = Object.assign({'Content-Type': 'application/json'}, getAuthHeaders());
      fetch(base + '/tools/__probe__/call', {
        method: 'POST',
        headers: probeHeaders,
        body: '{}'
      }).then(function(r) {
        executeEnabled = r.status !== 403;
      }).catch(function() {});
    })
    .catch(function(e) { loadingEl.textContent = 'Error: ' + e; });

  function toggleTool(li, name) {
    if (li.classList.contains('expanded')) {
      li.classList.remove('expanded');
      return;
    }
    // Collapse any other expanded tool
    var prev = toolsEl.querySelector('.tool-item.expanded');
    if (prev && prev !== li) prev.classList.remove('expanded');
    li.classList.add('expanded');
    var detailEl = li.querySelector('.tool-detail');
    // Load detail if not yet loaded
    if (!detailEl.getAttribute('data-loaded')) {
      loadDetail(li, name);
    }
  }

  function loadDetail(li, name) {
    var detailEl = li.querySelector('.tool-detail');
    detailEl.innerHTML = '<p style="color:#888;padding-top:12px">Loading...</p>';
    fetch(base + '/tools/' + encodeURIComponent(name), {headers: getAuthHeaders()})
      .then(function(r) { return r.json(); })
      .then(function(d) {
        detailEl.setAttribute('data-loaded', '1');
        var html =
          '<span class="schema-label">Input Schema</span>' +
          '<pre>' + esc(JSON.stringify(d.inputSchema, null, 2)) + '</pre>';

        if (d.annotations) {
          html += '<span class="schema-label">Annotations</span>' +
            '<pre>' + esc(JSON.stringify(d.annotations, null, 2)) + '</pre>';
        }

        html += '<div class="try-it">' +
          '<h3>Try it</h3>' +
          '<textarea class="input-editor">' +
          esc(JSON.stringify(defaultFromSchema(d.inputSchema), null, 2)) +
          '</textarea>' +
          '<button class="execute-btn">Execute</button>' +
          '<div class="result-area"></div>' +
          '</div>';

        detailEl.innerHTML = html;

        detailEl.querySelector('.execute-btn').onclick = function() {
          execTool(li, d.name);
        };

        if (executeEnabled === false) {
          var tryIt = detailEl.querySelector('.try-it');
          if (tryIt) tryIt.innerHTML =
            '<p class="exec-disabled">' +
            'Tool execution is disabled. ' +
            'Launch with --allow-execute to enable.</p>';
        }
      })
      .catch(function(e) {
        detailEl.setAttribute('data-loaded', '1');
        detailEl.innerHTML = '<p class="result-error" style="padding-top:12px">' +
          'Failed to load tool details: ' + esc(e.message) + '</p>';
      });
  }

  function execTool(li, name) {
    var detailEl = li.querySelector('.tool-detail');
    var btn = detailEl.querySelector('.execute-btn');
    var editor = detailEl.querySelector('.input-editor');
    var resultArea = detailEl.querySelector('.result-area');

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
    var authToken = (authInput.value || '').trim();
    var curlLines = ["curl -X POST '" + callUrl + "' \\\\"];
    curlLines.push("  -H 'Content-Type: application/json' \\\\");
    if (authToken) {
      var bearerVal = authToken.toLowerCase().indexOf('bearer ') === 0 ? authToken : 'Bearer ' + authToken;
      curlLines.push("  -H 'Authorization: " + bearerVal + "' \\\\");
    }
    curlLines.push("  -d '" + curlBody + "'");
    var curlCmd = curlLines.join("\\n");

    var fetchHeaders = Object.assign({'Content-Type': 'application/json'}, getAuthHeaders());
    fetch(base + '/tools/' + encodeURIComponent(name) + '/call', {
      method: 'POST',
      headers: fetchHeaders,
      body: bodyStr
    })
    .then(function(r) {
      if (r.status === 403) {
        executeEnabled = false;
        var tryIt = detailEl.querySelector('.try-it');
        if (tryIt) tryIt.innerHTML =
          '<p class="exec-disabled">' +
          'Tool execution is disabled. ' +
          'Launch with --allow-execute to enable.</p>';
        return null;
      }
      if (r.status === 401) {
        btn.disabled = false;
        btn.textContent = 'Execute';
        resultArea.innerHTML =
          '<p class="result-error">401 Unauthorized \\u2014 ' +
          'enter a valid Bearer token in the Authorization field above.</p>';
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
        '</code><button class="copy-btn">Copy</button></div></div>';

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

      var copyBtn = resultArea.querySelector('.copy-btn');
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
