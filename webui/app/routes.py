"""
Flask route definitions for HandBrake TSD Helper.

This module:
- Defines all HTTP endpoints (API + web UI)
- Uses helpers from jobs.py and presets.py
- Renders the single-page Web UI with embedded JS
"""

import os

from flask import (
    request,
    jsonify,
    render_template_string,
    send_file,
    abort,
)

from .config import (
    ROOTS,
    VIDEO_EXTS,
    PRESET_DIR,
    LOG_DIR,
)
from .jobs import (
    is_allowed_path,
    create_job,
    create_jobs_batch,
    get_job,
    list_jobs_for_api,
    cancel_job,
    remove_queued_job,
    clear_finished_jobs as clear_finished_jobs_core,
    get_queue_state,
    set_queue_paused,
)
from .presets import (
    list_preset_files,
    preset_config,
    save_preset_config,
    guess_preset_from_filename,
)

# -------------------------------------------------------------------
# HTML template (single-page UI)
# -------------------------------------------------------------------

INDEX_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>HandBrake TSD Helper</title>
  <style>
    :root {
      --bg: #121212;
      --bg-alt: #1e1e1e;
      --border: #333;
      --text: #e5e5e5;
      --accent: #00bcd4;
      --accent-soft: #004852;
    }

    body {
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      margin: 20px;
      background: var(--bg);
      color: var(--text);
    }

    h1, h2, h3 {
      margin-top: 0;
      color: #ffffff;
    }

    .row { margin-bottom: 10px; }

    select, input[type="text"], button {
      background: var(--bg-alt);
      color: var(--text);
      border: 1px solid var(--border);
      padding: 4px 8px;
      border-radius: 4px;
    }

    button {
      cursor: pointer;
      background: var(--accent-soft);
    }
    button:hover {
      background: var(--accent);
    }
    button:disabled {
      opacity: 0.5;
      cursor: default;
    }

    #dirs, #files {
      list-style: none;
      padding-left: 0;
      max-height: 300px;
      overflow-y: auto;
      border: 1px solid var(--border);
      margin: 0;
      background: var(--bg-alt);
    }
    #dirs li, #files li {
      padding: 4px 8px;
      cursor: pointer;
    }
    #dirs li:hover, #files li:hover { background: #2a2a2a; }
    #dirs li { font-weight: bold; }

    #statusBox {
      margin-top: 10px;
      white-space: pre-wrap;
      background: #000;
      color: #0f0;
      padding: 8px;
      font-size: 12px;
      max-height: 200px;
      overflow-y: auto;
      border-radius: 4px;
      border: 1px solid var(--border);
    }

    #progressBar {
      height: 14px;
    }

    #progressLabel {
      font-size: 14px;
      margin-left: 8px;
    }

    table {
      width: 100%;
      border-collapse: collapse;
      background: var(--bg-alt);
      font-size: 13px;
    }

    th, td {
      border: 1px solid var(--border);
      padding: 4px 6px;
      text-align: left;
    }

    th {
      background: #222;
    }

    .small {
      font-size: 12px;
      opacity: 0.85;
    }

    .job-status-done { color: #4caf50; }
    .job-status-error { color: #ff5252; }
    .job-status-running { color: #ffb300; }
    .job-status-canceled { color: #9e9e9e; }
    .job-status-queued { color: #42a5f5; }

    .section-card {
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 10px;
      background: rgba(255,255,255,0.03);
      margin-bottom: 16px;
    }

    a {
      color: var(--accent);
      text-decoration: none;
    }
    a:hover {
      text-decoration: underline;
    }

    .inline-input-group {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      align-items: center;
    }

    .inline-input-group select {
      flex: 1 1 auto;
      min-width: 180px;
    }
  </style>
</head>
<body>
  <h1>HandBrake One-shot Encoder (TSD)</h1>

  <div class="section-card">
    <h2>Browse & Select File</h2>
    <div class="row">
      <label for="rootSelect">Root:</label>
      <select id="rootSelect"></select>
      <button id="upBtn">Up</button>
    </div>

    <div class="row">
      <strong>Current path:</strong>
      <span id="currentPath" class="small"></span>
    </div>

    <div class="row" style="display:flex; gap:10px;">
      <div style="flex:1;">
        <strong>Folders</strong>
        <ul id="dirs"></ul>
      </div>
      <div style="flex:1;">
        <strong>Video files</strong>
        <ul id="files"></ul>
      </div>
    </div>

    <div class="row">
      <label>Selected file:</label>
      <input type="text" id="selectedFile" style="width:80%;" readonly>
    </div>

    <div class="row">
      <label for="presetSelect">Preset mode:</label>
      <select id="presetSelect">
        <option value="auto">Auto by filename (1080p vs 2160p/4K)</option>
        <option value="1080">Force 1080p preset</option>
        <option value="4k">Force 4K preset</option>
      </select>
    </div>

    <div class="row">
      <button id="startBtn">Start Encode (queue)</button>
      <button id="cancelBtn" disabled>Cancel Encode</button>
    </div>

    <div class="row">
      <button id="batchEncodeBtn">Batch encode ALL videos in this folder (queued)</button>
      <button id="batchEncodeRecursiveBtn">Batch encode this folder + subfolders (queued)</button>
    </div>

    <div class="row">
      <progress id="progressBar" max="100" value="0" style="width:100%; display:none;"></progress>
      <span id="progressLabel"></span>
    </div>

    <div class="row">
      <strong>Status / Log</strong>
      <div id="statusText" class="small"></div>
      <div id="statusBox"></div>
    </div>
  </div>

  <div class="section-card">
    <h2>Batch Rename Helper</h2>
    <p class="small">
      This will rename <strong>all video files</strong> in the current folder to add
      <code>-TSD</code> before the extension (only if they don't already have it).
    </p>
    <button id="batchRenameBtn">Batch rename visible folder to -TSD</button>
    <div id="batchRenameResult" class="small"></div>
  </div>

  <div class="section-card">
    <h2>Preset Settings (saved defaults for Auto mode)</h2>
    <p class="small">
      These control which HandBrake <code>.json</code> preset file is used when a job is tagged
      as 1080p or 4K/2160p. The preset <strong>name</strong> is auto-detected from inside
      the JSON file; you only have to pick the file.
      The dropdowns are populated from the <code>{{ preset_dir }}</code> folder.
    </p>

    <div class="row">
      <h3 style="margin-bottom:4px;">Default 1080p preset file</h3>
      <div class="inline-input-group">
        <label>HB_PRESET_FILE:</label>
        <select id="preset1080FileSelect"></select>
      </div>
    </div>

    <div class="row" style="margin-top:10px;">
      <h3 style="margin-bottom:4px;">Default 4K / 2160p preset file</h3>
      <div class="inline-input-group">
        <label>HB_PRESET_FILE:</label>
        <select id="preset4kFileSelect"></select>
      </div>
    </div>

    <div class="row" style="margin-top:10px;">
      <button id="savePresetConfigBtn">Save preset settings</button>
      <span id="presetSaveStatus" class="small"></span>
    </div>
  </div>

  <div class="section-card">
    <h2>Job History (persists across restarts, queued)</h2>
    <div class="row" style="display:flex; gap:10px; align-items:center;">
      <button id="pauseQueueBtn">Pause queue</button>
      <span id="queueStatusLabel" class="small"></span>
      <button id="clearFinishedBtn" style="margin-left:auto;">Clear finished jobs (done/error)</button>
    </div>
    <table>
      <thead>
        <tr>
          <th>Job ID</th>
          <th>File</th>
          <th>Preset</th>
          <th>Status</th>
          <th>Return</th>
          <th>Progress</th>
          <th>Log</th>
          <th>Actions</th>
        </tr>
      </thead>
      <tbody id="jobsTableBody">
      </tbody>
    </table>
  </div>

<script>
const roots = {{ roots | tojson }};
const presetFiles = {{ preset_files | tojson }};
let currentPath = roots[0][0];
let currentJobId = null;
let statusTimer = null;
let jobsTimer = null;

function populateRoots() {
  const select = document.getElementById('rootSelect');
  select.innerHTML = '';
  roots.forEach(([path, label], idx) => {
    const opt = document.createElement('option');
    opt.value = path;
    opt.textContent = label;
    if (idx === 0) opt.selected = true;
    select.appendChild(opt);
  });
}

function populatePresetFileSelect(selectId, currentFile) {
  const select = document.getElementById(selectId);
  select.innerHTML = '';

  let hasCurrent = false;
  presetFiles.forEach(path => {
    const opt = document.createElement('option');
    opt.value = path;
    opt.textContent = path.split('/').pop();
    if (currentFile && path === currentFile) {
      opt.selected = true;
      hasCurrent = true;
    }
    select.appendChild(opt);
  });

  if (currentFile && !hasCurrent) {
    const opt = document.createElement('option');
    opt.value = currentFile;
    opt.textContent = currentFile + ' (custom / not found)';
    opt.selected = true;
    select.appendChild(opt);
  }
}

function loadDir(path) {
  fetch('/list?path=' + encodeURIComponent(path))
    .then(r => r.json())
    .then(data => {
      if (data.error) {
        alert(data.error);
        return;
      }
      currentPath = data.path;
      document.getElementById('currentPath').textContent = data.path;

      const dirsUl = document.getElementById('dirs');
      dirsUl.innerHTML = '';
      data.dirs.forEach(name => {
        const li = document.createElement('li');
        li.textContent = name;
        li.onclick = () => {
          const newPath = data.path.replace(/\\/$/, '') + '/' + name;
          loadDir(newPath);
        };
        dirsUl.appendChild(li);
      });

      const filesUl = document.getElementById('files');
      filesUl.innerHTML = '';
      data.files.forEach(name => {
        const li = document.createElement('li');
        li.textContent = name;
        li.onclick = () => {
          const fullPath = data.path.replace(/\\/$/, '') + '/' + name;
          document.getElementById('selectedFile').value = fullPath;
        };
        filesUl.appendChild(li);
      });
    })
    .catch(err => {
      console.error(err);
      alert('Error loading directory');
    });
}

function goUp() {
  const rootPaths = roots.map(r => r[0]);
  if (rootPaths.includes(currentPath)) {
    return; // already at root
  }
  const parts = currentPath.split('/').filter(Boolean);
  parts.pop();
  const newPath = '/' + parts.join('/');
  loadDir(newPath || currentPath);
}

function startEncode() {
  const src = document.getElementById('selectedFile').value;
  const preset = document.getElementById('presetSelect').value;
  if (!src) {
    alert('Pick a video file first.');
    return;
  }
  fetch('/encode', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({src, preset})
  })
  .then(r => r.json())
  .then(data => {
    if (data.error) {
      alert(data.error);
      return;
    }
    currentJobId = data.job_id;
    document.getElementById('statusText').textContent = "Job queued: " + currentJobId;
    document.getElementById('statusBox').textContent = '';
    const pb = document.getElementById('progressBar');
    pb.style.display = 'block';
    pb.value = 0;
    document.getElementById('progressLabel').textContent = 'Queued';

    document.getElementById('cancelBtn').disabled = false;

    if (statusTimer) clearInterval(statusTimer);
    statusTimer = setInterval(checkStatus, 2000);
    refreshJobs();
  })
  .catch(err => {
    console.error(err);
    alert('Error starting encode');
  });
}

function cancelEncode() {
  if (!currentJobId) return;
  fetch('/cancel/' + currentJobId, { method: 'POST' })
    .then(r => r.json())
    .then(data => {
      if (data.error) {
        alert(data.error);
        return;
      }
      document.getElementById('statusText').textContent = 'Status: canceled';
      document.getElementById('cancelBtn').disabled = true;
      const pb = document.getElementById('progressBar');
      pb.value = 0;
      document.getElementById('progressLabel').textContent = 'Canceled';
      if (statusTimer) clearInterval(statusTimer);
      refreshJobs();
    })
    .catch(err => {
      console.error(err);
    });
}

function checkStatus() {
  if (!currentJobId) return;
  fetch('/status/' + currentJobId)
    .then(r => r.json())
    .then(data => {
      if (data.error) {
        document.getElementById('statusText').textContent = 'Error: ' + data.error;
        clearInterval(statusTimer);
        return;
      }

      const statusText = 'Status: ' + data.status +
        (data.returncode !== null && data.returncode !== undefined
           ? (' (code ' + data.returncode + ')')
           : '');
      document.getElementById('statusText').textContent = statusText;
      document.getElementById('statusBox').textContent = data.log || '';

      const pb = document.getElementById('progressBar');
      if (data.progress !== undefined && data.progress !== null) {
        pb.value = data.progress;
        document.getElementById('progressLabel').textContent =
          data.progress.toFixed(1) + '%';
      }

      if (data.status === 'done' || data.status === 'error' || data.status === 'canceled') {
        document.getElementById('cancelBtn').disabled = true;
        clearInterval(statusTimer);
      }

      refreshJobs();
    })
    .catch(err => {
      console.error(err);
      clearInterval(statusTimer);
    });
}

function refreshJobs() {
  fetch('/jobs')
    .then(r => r.json())
    .then(data => {
      if (data.error) return;

      const tbody = document.getElementById('jobsTableBody');
      tbody.innerHTML = '';

      data.jobs.forEach(job => {
        const tr = document.createElement('tr');

        const tdId = document.createElement('td');
        tdId.textContent = job.id;
        tdId.className = "small";
        tr.appendChild(tdId);

        const tdSrc = document.createElement('td');
        tdSrc.textContent = job.src;
        tdSrc.className = "small";
        tr.appendChild(tdSrc);

        const tdPreset = document.createElement('td');
        tdPreset.textContent = job.preset;
        tr.appendChild(tdPreset);

        const tdStatus = document.createElement('td');
        tdStatus.textContent = job.status;
        if (job.status === 'done') tdStatus.className = 'job-status-done';
        else if (job.status === 'error') tdStatus.className = 'job-status-error';
        else if (job.status === 'running') tdStatus.className = 'job-status-running';
        else if (job.status === 'canceled') tdStatus.className = 'job-status-canceled';
        else if (job.status === 'queued') tdStatus.className = 'job-status-queued';
        tr.appendChild(tdStatus);

        const tdRc = document.createElement('td');
        tdRc.textContent = job.returncode === null ? '' : job.returncode;
        tr.appendChild(tdRc);

        const tdProg = document.createElement('td');
        tdProg.textContent = job.progress != null ? job.progress.toFixed(1) + '%' : '';
        tr.appendChild(tdProg);

        const tdLog = document.createElement('td');
        if (job.has_log) {
          const a = document.createElement('a');
          a.href = '/job_log/' + encodeURIComponent(job.id);
          a.textContent = 'Download';
          a.target = '_blank';
          tdLog.appendChild(a);
        } else {
          tdLog.textContent = '';
        }
        tr.appendChild(tdLog);

        // Actions column: remove from queue if queued
        const tdActions = document.createElement('td');
        if (job.status === 'queued') {
          const removeBtn = document.createElement('button');
          removeBtn.textContent = 'Remove from queue';
          removeBtn.onclick = () => {
            if (!confirm('Remove this queued job?')) return;
            fetch('/remove/' + encodeURIComponent(job.id), { method: 'POST' })
              .then(r => r.json())
              .then(data => {
                if (data.error) {
                  alert(data.error);
                  return;
                }
                refreshJobs();
              })
              .catch(err => {
                console.error(err);
                alert('Failed to remove job');
              });
          };
          tdActions.appendChild(removeBtn);
        } else {
          tdActions.textContent = '';
        }
        tr.appendChild(tdActions);

        tbody.appendChild(tr);
      });
    })
    .catch(err => {
      console.error(err);
    });
}

function batchRename() {
  if (!currentPath) {
    alert("No current path selected.");
    return;
  }

  if (!confirm(
    "This will rename all video files in:\\n" +
    currentPath +
    "\\n\\nFiles will get -TSD added before the extension. Continue?"
  )) {
    return;
  }

  fetch('/batch_rename', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({path: currentPath})
  })
    .then(r => r.json())
    .then(data => {
      if (data.error) {
        alert(data.error);
        return;
      }
      const text = "Renamed " + data.renamed_count +
        " file(s). Skipped " + data.skipped_count + ".";
      document.getElementById('batchRenameResult').textContent = text;
      loadDir(currentPath);
    })
    .catch(err => {
      console.error(err);
      alert("Batch rename failed");
    });
}

function batchEncode(folderOnly) {
  if (!currentPath) {
    alert("No current path selected.");
    return;
  }

  const preset = document.getElementById('presetSelect').value;

  const msg = folderOnly
    ? "This will QUEUE encodes for ALL video files directly in:\\n" +
      currentPath +
      "\\n\\nPreset: " + preset + "\\n\\nThey will run one-by-one in order. Continue?"
    : "This will QUEUE encodes for ALL video files in this folder AND ALL SUBFOLDERS:\\n" +
      currentPath +
      "\\n\\nPreset: " + preset + "\\n\\nThey will run one-by-one in order. Continue?";

  if (!confirm(msg)) {
    return;
  }

  const url = folderOnly ? '/batch_encode' : '/batch_encode_recursive';

  fetch(url, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({path: currentPath, preset})
  })
    .then(r => r.json())
    .then(data => {
      if (data.error) {
        alert(data.error);
        return;
      }
      alert("Queued " + data.count + " file(s) for encode.");
      refreshJobs();
    })
    .catch(err => {
      console.error(err);
      alert("Batch encode failed");
    });
}

function clearFinishedJobs() {
  if (!confirm("This will remove all jobs with status 'done' or 'error' from history and delete their log files. Continue?")) {
    return;
  }

  fetch('/clear_finished_jobs', {
    method: 'POST'
  })
    .then(r => r.json())
    .then(data => {
      if (data.error) {
        alert(data.error);
        return;
      }
      refreshJobs();
    })
    .catch(err => {
      console.error(err);
      alert('Failed to clear finished jobs');
    });
}

function refreshQueueState() {
  fetch('/queue_state')
    .then(r => r.json())
    .then(data => {
      const label = document.getElementById('queueStatusLabel');
      const btn = document.getElementById('pauseQueueBtn');
      if (!data || typeof data.paused === 'undefined') return;

      if (data.paused) {
        label.textContent = 'Queue is paused – no new jobs will start.';
        btn.textContent = 'Resume queue';
      } else {
        label.textContent = 'Queue is running.';
        btn.textContent = 'Pause queue';
      }
    })
    .catch(err => {
      console.error(err);
    });
}

function toggleQueuePause() {
  fetch('/pause_queue', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({paused: null})
  })
    .then(r => r.json())
    .then(data => {
      refreshQueueState();
    })
    .catch(err => {
      console.error(err);
      alert('Failed to toggle queue pause');
    });
}

function loadPresetConfigUI() {
  fetch('/preset_config')
    .then(r => r.json())
    .then(data => {
      if (data.error) return;
      const cfg = data.config || {};
      const p1080 = cfg["1080"] || {};
      const p4k = cfg["4k"] || {};

      populatePresetFileSelect('preset1080FileSelect', p1080.file || '');
      populatePresetFileSelect('preset4kFileSelect', p4k.file || '');
    })
    .catch(err => {
      console.error(err);
    });
}

function savePresetConfigUI() {
  const body = {
    "1080": {
      "file": document.getElementById('preset1080FileSelect').value
    },
    "4k": {
      "file": document.getElementById('preset4kFileSelect').value
    }
  };

  fetch('/preset_config', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body)
  })
    .then(r => r.json())
    .then(data => {
      const statusEl = document.getElementById('presetSaveStatus');
      if (data.error) {
        statusEl.textContent = 'Failed to save preset settings: ' + data.error;
        return;
      }
      statusEl.textContent = 'Preset settings saved.';
      setTimeout(() => { statusEl.textContent = ''; }, 4000);
    })
    .catch(err => {
      console.error(err);
      const statusEl = document.getElementById('presetSaveStatus');
      statusEl.textContent = 'Failed to save preset settings.';
      setTimeout(() => { statusEl.textContent = ''; }, 4000);
    });
}

document.addEventListener('DOMContentLoaded', () => {
  populateRoots();
  const initialRoot = roots[0][0];
  loadDir(initialRoot);

  document.getElementById('rootSelect').addEventListener('change', (e) => {
    loadDir(e.target.value);
  });

  document.getElementById('upBtn').onclick = goUp;
  document.getElementById('startBtn').onclick = startEncode;
  document.getElementById('cancelBtn').onclick = cancelEncode;
  document.getElementById('batchRenameBtn').onclick = batchRename;
  document.getElementById('batchEncodeBtn').onclick = () => batchEncode(true);
  document.getElementById('batchEncodeRecursiveBtn').onclick = () => batchEncode(false);
  document.getElementById('clearFinishedBtn').onclick = clearFinishedJobs;
  document.getElementById('pauseQueueBtn').onclick = toggleQueuePause;
  document.getElementById('savePresetConfigBtn').onclick = savePresetConfigUI;

  loadPresetConfigUI();
  refreshJobs();
  refreshQueueState();

  jobsTimer = setInterval(() => {
    refreshJobs();
    refreshQueueState();
  }, 5000);
});
</script>

</body>
</html>
"""


# -------------------------------------------------------------------
# Route registration
# -------------------------------------------------------------------

def register_routes(app):
    """
    Attach all routes to the given Flask app.
    """

    # ------------- UI -------------

    @app.route("/")
    def index():
        preset_files = list_preset_files()
        return render_template_string(
            INDEX_HTML,
            roots=ROOTS,
            preset_files=preset_files,
            preset_dir=PRESET_DIR,
        )

    # ------------- Directory listing -------------

    @app.route("/list")
    def list_path():
        path = request.args.get("path")
        if not path:
            return jsonify(error="missing path"), 400

        if not is_allowed_path(path) or not os.path.isdir(path):
            return jsonify(error="path not allowed or not a directory"), 400

        try:
            entries = os.listdir(path)
        except Exception as e:
            return jsonify(error=str(e)), 500

        dirs = sorted([e for e in entries if os.path.isdir(os.path.join(path, e))])
        files = sorted(
            [
                e
                for e in entries
                if os.path.isfile(os.path.join(path, e))
                and e.lower().endswith(VIDEO_EXTS)
            ]
        )

        return jsonify(path=path, dirs=dirs, files=files)

    # ------------- Single encode -------------

    @app.route("/encode", methods=["POST"])
    def encode():
        data = request.get_json(force=True)
        src = data.get("src")
        preset = data.get("preset") or "1080"

        if not src or not os.path.isfile(src):
            return jsonify(error="invalid src"), 400

        if not is_allowed_path(src):
            return jsonify(error="path not allowed"), 400

        if preset not in ("1080", "4k", "auto"):
            return jsonify(error="invalid preset"), 400

        base = os.path.basename(src)
        name_only, ext = os.path.splitext(base)
        if name_only.lower().endswith("-tsd"):
            return jsonify(error="file already tagged -TSD, not queuing"), 400

        if preset == "auto":
            preset = guess_preset_from_filename(base)

        job_id = create_job(src, preset)
        return jsonify(job_id=job_id)

    # ------------- Job status -------------

    @app.route("/status/<job_id>")
    def status(job_id):
        job = get_job(job_id)
        if not job:
            return jsonify(error="job not found"), 404
        return jsonify(job)

    # ------------- Cancel job -------------

    @app.route("/cancel/<job_id>", methods=["POST"])
    def cancel_route(job_id):
        ok, err = cancel_job(job_id)
        if not ok:
            return jsonify(error=err or "cancel failed"), 400
        return jsonify(ok=True, job_id=job_id)

    # ------------- Job list -------------

    @app.route("/jobs")
    def jobs_list():
        items = list_jobs_for_api()
        return jsonify(jobs=items)

    # ------------- Job log download -------------

    @app.route("/job_log/<job_id>")
    def job_log(job_id):
        if not get_job(job_id):
            abort(404)
        log_path = os.path.join(LOG_DIR, f"{job_id}.log")
        if not os.path.isfile(log_path):
            abort(404)
        return send_file(
            log_path,
            mimetype="text/plain",
            as_attachment=True,
            download_name=f"{job_id}.log",
        )

    # ------------- Batch rename -------------

    @app.route("/batch_rename", methods=["POST"])
    def batch_rename():
        data = request.get_json(force=True)
        path = data.get("path")

        if not path or not os.path.isdir(path):
            return jsonify(error="invalid path"), 400

        if not is_allowed_path(path):
            return jsonify(error="path not allowed"), 400

        renamed = 0
        skipped = 0

        try:
            for entry in os.listdir(path):
                full = os.path.join(path, entry)
                if not os.path.isfile(full):
                    continue

                if not entry.lower().endswith(VIDEO_EXTS):
                    continue

                name, ext = os.path.splitext(entry)
                if name.lower().endswith("-tsd"):
                    skipped += 1
                    continue

                new_name = f"{name}-TSD{ext}"
                new_full = os.path.join(path, new_name)

                if os.path.exists(new_full):
                    skipped += 1
                    continue

                os.rename(full, new_full)
                renamed += 1
        except Exception as e:
            return jsonify(error=str(e)), 500

        return jsonify(renamed_count=renamed, skipped_count=skipped)

    # ------------- Batch encode (non-recursive) -------------

    @app.route("/batch_encode", methods=["POST"])
    def batch_encode():
        data = request.get_json(force=True)
        path = data.get("path")
        preset = data.get("preset") or "1080"

        if not path or not os.path.isdir(path):
            return jsonify(error="invalid path"), 400

        if not is_allowed_path(path):
            return jsonify(error="path not allowed"), 400

        if preset not in ("1080", "4k", "auto"):
            return jsonify(error="invalid preset"), 400

        files = sorted(
            [
                e
                for e in os.listdir(path)
                if os.path.isfile(os.path.join(path, e))
                and e.lower().endswith(VIDEO_EXTS)
                and not os.path.splitext(e)[0].lower().endswith("-tsd")
            ]
        )

        if not files:
            return jsonify(error="no video files found"), 400

        to_create = []
        for entry in files:
            src = os.path.join(path, entry)
            if preset == "auto":
                effective_preset = guess_preset_from_filename(entry)
            else:
                effective_preset = preset
            to_create.append((src, effective_preset))

        count = create_jobs_batch(to_create)
        return jsonify(count=count)

    # ------------- Batch encode (recursive) -------------

    @app.route("/batch_encode_recursive", methods=["POST"])
    def batch_encode_recursive():
        data = request.get_json(force=True)
        path = data.get("path")
        preset = data.get("preset") or "1080"

        if not path or not os.path.isdir(path):
            return jsonify(error="invalid path"), 400

        if not is_allowed_path(path):
            return jsonify(error="path not allowed"), 400

        if preset not in ("1080", "4k", "auto"):
            return jsonify(error="invalid preset"), 400

        to_create = []
        for root, dirs, files in os.walk(path):
            for entry in files:
                if not entry.lower().endswith(VIDEO_EXTS):
                    continue

                name, ext = os.path.splitext(entry)
                if name.lower().endswith("-tsd"):
                    continue

                src = os.path.join(root, entry)
                if preset == "auto":
                    effective_preset = guess_preset_from_filename(entry)
                else:
                    effective_preset = preset

                to_create.append((src, effective_preset))

        if not to_create:
            return jsonify(error="no video files found"), 400

        count = create_jobs_batch(to_create)
        return jsonify(count=count)

    # ------------- Clear finished jobs -------------

    @app.route("/clear_finished_jobs", methods=["POST"])
    def clear_finished_jobs_route():
        removed = clear_finished_jobs_core()
        return jsonify(removed=removed)

    # ------------- Preset config (1080 / 4k mapping) -------------

    @app.route("/preset_config", methods=["GET", "POST"])
    def preset_config_route():
        from .presets import preset_config as pc  # alias for clarity
        global preset_config

        if request.method == "GET":
            exposed = {
                "1080": {"file": pc["1080"]["file"]},
                "4k": {"file": pc["4k"]["file"]},
            }
            return jsonify(config=exposed)

        data = request.get_json(force=True) or {}
        changed = False

        for key in ("1080", "4k"):
            if key in data and isinstance(data[key], dict):
                current = pc.get(key)
                if not current:
                    continue
                file_val = data[key].get("file") or current["file"]
                name_val = current["name"]
                pc[key] = {"file": file_val, "name": name_val}
                changed = True

        if changed:
            save_preset_config()

        exposed = {
            "1080": {"file": pc["1080"]["file"]},
            "4k": {"file": pc["4k"]["file"]},
        }
        return jsonify(config=exposed)

    # ------------- Queue state (pause / resume) -------------

    @app.route("/queue_state")
    def queue_state():
        paused = get_queue_state()
        return jsonify(paused=paused)

    @app.route("/pause_queue", methods=["POST"])
    def pause_queue():
        data = request.get_json(silent=True) or {}
        if "paused" in data and isinstance(data["paused"], bool):
            new_state = set_queue_paused(data["paused"])
        else:
            new_state = set_queue_paused(None)
        return jsonify(paused=new_state)

    # ------------- Remove queued job -------------

    @app.route("/remove/<job_id>", methods=["POST"])
    def remove_job_route(job_id):
        ok, err = remove_queued_job(job_id)
        if not ok:
            return jsonify(error=err or "remove failed"), 400
        return jsonify(ok=True, job_id=job_id)
