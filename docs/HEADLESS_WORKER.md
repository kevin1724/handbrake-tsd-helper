# Headless Worker Setup

This guide installs a ByteSqueeze headless worker, maps its temporary work
drive, pairs it with the main controller, and configures safe multi-encode
capacity. The main controller owns the website, library, presets, queue, and
worker settings. The worker has no website and never needs the media library
mounted.

## How it works

1. The main node securely transfers a source file and its exact preset plan to
   the worker.
2. The worker downloads it under `/work/jobs`, encodes locally, and reports
   progress to the main node.
3. The worker uploads the completed file. The main node verifies it before
   replacing anything beside the original media.
4. Temporary job files are removed after a verified upload. If the main node
   is offline, the completed output stays on the worker and retries later.

The worker's `/work` mount contains both durable pairing/queue state and
temporary job data:

```text
/work/state/    pairing credentials, settings, queue state, and logs
/work/jobs/     downloaded sources and temporary encoded outputs
```

Always map the whole `/work` directory. Mapping only `/work/jobs` would leave
pairing state inside the disposable container layer.

## Requirements

- Docker Engine with Compose v2
- A fixed LAN address or DNS name reachable from the main node
- TCP port `8082` available on the worker host
- A fast writable drive with enough free space for the source plus its
  temporary output; allow at least twice the size of the largest queued file
- Optional Intel Quick Sync device at `/dev/dri` for QSV encoding

## 1. Map the temporary work drive

The supplied `docker-compose.worker.yml` maps the host path in
`TSD_WORKER_WORK_DIR` to `/work` inside the container.

### Linux

```bash
sudo mkdir -p /mnt/fast-ssd/bytesqueeze-worker
sudo chown -R "$(id -u):$(id -g)" /mnt/fast-ssd/bytesqueeze-worker
export TSD_WORKER_WORK_DIR=/mnt/fast-ssd/bytesqueeze-worker
```

Put the value in a `.env` file beside `docker-compose.worker.yml` to keep it
across reboots:

```dotenv
TSD_WORKER_WORK_DIR=/mnt/fast-ssd/bytesqueeze-worker
TSD_WORKER_NAME=Garage QSV Worker
TSD_WORKER_PORT=8082
TSD_HW_DECODE=auto
TZ=America/Los_Angeles
```

### Unraid

Use a cache or pool path so active encodes do not run on the parity-protected
array:

```dotenv
TSD_WORKER_WORK_DIR=/mnt/cache/appdata/bytesqueeze-worker
```

If using the Unraid Docker form instead of Compose, add one path mapping:

| Setting | Value |
|---|---|
| Host path | `/mnt/cache/appdata/bytesqueeze-worker` |
| Container path | `/work` |
| Access mode | Read/Write |

Also map `/dev/dri` when using Intel Quick Sync.

### Windows with Docker Desktop

Create a local folder, share the drive with Docker Desktop if prompted, then
set the variable in PowerShell before starting Compose:

```powershell
New-Item -ItemType Directory -Force -Path 'D:\ByteSqueezeWorker'
$env:TSD_WORKER_WORK_DIR='D:\ByteSqueezeWorker'
docker compose -f docker-compose.worker.yml up -d
```

A local SSD is preferred. SMB/NFS paths can work, but a network interruption
can stall an encode and they are usually slower for temporary I/O.

## 2. Start the worker

Stable channel:

```bash
docker compose -f docker-compose.worker.yml pull
docker compose -f docker-compose.worker.yml up -d
docker compose -f docker-compose.worker.yml ps
```

Beta channel:

```bash
docker compose -f docker-compose.worker.yml -f docker-compose.worker.beta.yml pull
docker compose -f docker-compose.worker.yml -f docker-compose.worker.beta.yml up -d
```

For Intel Quick Sync, uncomment the `/dev/dri` device mapping in
`docker-compose.worker.yml` before starting the container.

Verify health from another machine:

```bash
curl http://WORKER-IP:8082/api/health
```

The response should identify `bytesqueeze-headless-worker`, show free work-drive
space, and include the active encoding policy.

## 3. Pair the worker to the main node

Read the one-time code:

```bash
docker logs bytesqueeze-worker
```

The banner contains a code such as `ABCDE-FGHJK`. It expires after one hour.
Generate a fresh code without restarting or interrupting active encodes:

```bash
docker exec bytesqueeze-worker python -m worker.app pairing-code
```

The newest code replaces any older unused code. To choose a shorter lifetime,
pass `--ttl-seconds 900` (accepted range: 300–3600 seconds).

On the main node:

1. Open **Settings → Linked Workers**.
2. Enter the worker URL, for example `http://192.168.1.50:8082`.
3. Enter the code from the worker logs and an optional friendly name.
4. Select **Pair and verify**.
5. Confirm the worker shows **online**, **headless**, and its work-drive path.

The pairing secret and recovery token are stored under `/work/state`; normal
container upgrades do not require pairing again.

## 4. Configure multi-encode from the main node

Under **Settings → Linked Workers**, each worker has a **Simultaneous hardware
transcodes** selector. Choose a value and select **Save GPU capacity**.

- The safe default is `1`.
- Start with `2` for a modern Intel Quick Sync worker, then watch temperatures,
  GPU utilization, throughput, and quality.
- Hardware jobs can fill the configured slots.
- CPU/software jobs always run alone, regardless of the GPU setting.
- Lowering the value does not cancel running work; it prevents another job
  from starting until usage drops below the new limit.
- The main node stores the setting and sends the current encoding and output
  safety policy to the worker. There is no separate worker settings website.

Use a hardware Smart Preset or a preset whose HandBrake `VideoEncoder` is QSV,
NVENC, AMD/AMF, VideoToolbox, or VAAPI. Software encoders such as x264, x265,
and SVT-AV1 intentionally remain single-job.

For Intel QSV jobs, `TSD_HW_DECODE=auto` (the default) enables QSV decoding for
supported H.264 and HEVC sources. Use `qsv` to prefer QSV decode independently
of the selected encoder, or `off` to force software decode. Unsupported streams
fall back to software automatically, and a failed QSV decode attempt is retried
once with software decoding while preserving the selected QSV encoder.

The worker defaults to QSV adapter `0`, `/dev/dri/renderD128`, and the Intel
`iHD` VA driver. `TSD_QSV_ADAPTER`, `TSD_QSV_RENDER_DEVICE`, and
`LIBVA_DRIVER_NAME` can override those values on unusual multi-GPU systems.
At startup and before each QSV encode, logs show `ls -l /dev/dri`, the selected
render node, active VA driver, selected adapter, and VAAPI/QSV preflight result.
HandBrake's adapter index is resolved to the detected DRM render node, so VAAPI
is never initialized with the invalid device name `0`.
On Linux, HandBrake may transfer QSV-decoded frames through system memory for
software filters. The worker distinguishes that verified hardware decode plus
hardware encode path from a genuinely encode-only job in its log message.

## 5. Send work

From Library or Queue on the main node, choose **Best worker** or select the
named worker. No controller media folder needs to be mounted on a headless
worker—the secure remote-transfer flow handles source and result movement.
Worker rows are included in the main **Jobs** screen. **Clear finished** clears
completed and failed history on both the controller and linked workers without
touching queued, running, or waiting-to-upload work.

## Updating

```bash
docker compose -f docker-compose.worker.yml pull
docker compose -f docker-compose.worker.yml up -d
```

The `/work` bind mount preserves pairing state and any completed output waiting
to upload while the container is replaced.

## Troubleshooting

### Worker will not pair

```bash
docker logs --tail 200 bytesqueeze-worker
curl http://WORKER-IP:8082/api/node/discovery
```

Confirm the main node can reach the worker address and port, use the newest
unexpired code, and make sure a reverse proxy is not removing node-signature
headers.

Create a replacement pairing code without restarting the worker:

```bash
docker exec bytesqueeze-worker python -m worker.app pairing-code
```

### A remote job fails before encoding starts

Open **Jobs → Linked Nodes** on the main node. Failed worker rows now show the
specific transfer or HandBrake error, a recent log tail, and a full worker-log
download. The same diagnostics remain available with:

```bash
docker logs --tail 300 bytesqueeze-worker
```

The worker learns the controller address from the authenticated connection it
actually receives. This avoids sending large source downloads to a browser-only
VPN, loopback, or reverse-proxy address. Interrupted downloads are retried three
times with a five-minute socket timeout by default. Slow storage can override
those defaults in the Compose `.env` file:

```dotenv
TSD_WORKER_TRANSFER_TIMEOUT_SECONDS=600
TSD_WORKER_TRANSFER_ATTEMPTS=5
```

### GPU jobs still run one at a time

1. Confirm the worker uses the new headless image and reports the
   `gpu-multi-encode` capability.
2. Save a value greater than one under **Settings → Linked Workers**.
3. Confirm the preset actually uses a hardware encoder.
4. For Intel, confirm `/dev/dri` is mapped and run:

   ```bash
   docker exec -it bytesqueeze-worker check-qsv
   ```

### QSV encoding works but decoding stays on the CPU

Open the job log from the main Jobs screen. A supported active decode path
contains ByteSqueeze's `Hardware decode: QSV` request plus HandBrake markers
such as a nonzero `HardwareDecode`, `QSV Decode: true`, or `using full QSV`.
The worker records `software fallback (<reason>)` when the source is unsupported
or HandBrake cannot activate QSV decoding.

Confirm `TSD_HW_DECODE` is `auto` or `qsv`, the preset's actual encoder is a QSV
encoder, and `/dev/dri` is mapped. Then run `check-qsv` to inspect the render
device, Intel runtime packages, and HandBrake QSV encoders.

### Work drive fills up

Completed outputs remain under `/work/jobs` when the main node is unreachable.
Restore the main node connection so uploads can finish. Do not manually delete
a current job directory unless that work can be discarded. Check capacity with:

```bash
docker exec bytesqueeze-worker df -h /work
docker logs --tail 200 bytesqueeze-worker
```

### Upgrade without losing pairing

Never recreate the worker without its `/work` mapping. If the mapping changed,
restore the old `/work/state` directory or pair the replacement worker again.
