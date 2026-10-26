import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const directory = process.argv[2]
  ? path.resolve(process.argv[2])
  : path.join(root, 'node_modules/electron-updater')
const packageInfo = JSON.parse(await fs.readFile(path.join(directory, 'package.json'), 'utf8'))
if (packageInfo.version !== '6.8.9')
  throw new Error(`Unsupported electron-updater version: ${packageInfo.version}`)
async function patch(name, replacements) {
  const file = path.join(directory, 'out/differentialDownloader', name + '.js')
  let source = (await fs.readFile(file, 'utf8')).replaceAll('\r\n', '\n')
  for (const [original, replacement] of replacements) {
    if (source.includes(replacement)) continue
    if (!source.includes(original))
      throw new Error(`electron-updater patch marker missing: ${name}: ${original.slice(0, 70)}`)
    source = source.replaceAll(original, replacement)
  }
  await fs.writeFile(file, source, 'utf8')
}
await patch('multipleRangeDownloader', [
  ['const nextOffset = taskOffset + 1000;', 'const nextOffset = taskOffset + 200;'],
  [
    '    const w = (taskOffset) => {',
    `    const total = tasks.reduce((sum, task) => sum + (task.kind === downloadPlanBuilder_1.OperationKind.DOWNLOAD ? task.end - task.start : 0), 0);
    let transferred = 0, delta = 0, lastProgress = Date.now();
    const started = lastProgress;
    const onProgress = (info) => {
        transferred += info.delta;
        delta += info.delta;
        const now = Date.now();
        if (now - lastProgress >= 1000 || transferred === total) {
            differentialDownloader.options.onProgress?.({
                total, transferred, delta, percent: total ? transferred / total * 100 : 100,
                bytesPerSecond: Math.round(transferred * 1000 / Math.max(1, now - started))
            });
            delta = 0;
            lastProgress = now;
        }
    };
    const w = (taskOffset) => {`
  ],
  [
    '    const w = (taskOffset) => {',
    `    const w = (taskOffset) => {
        if (differentialDownloader.options.cancellationToken.cancelled) {
            reject(new builder_util_runtime_1.CancellationError());
            return;
        }`
  ],
  [
    '    differentialDownloader.httpExecutor.addErrorAndTimeoutHandlers(request, reject);',
    `    watchCancellation(request, differentialDownloader.options.cancellationToken, reject);
    differentialDownloader.httpExecutor.addErrorAndTimeoutHandlers(request, reject);`
  ],
  ['}, out, () => w(nextOffset), reject);', '}, out, () => w(nextOffset), reject, onProgress);'],
  [
    'function doExecuteTasks(differentialDownloader, options, out, resolve, reject) {',
    'function doExecuteTasks(differentialDownloader, options, out, resolve, reject, onProgress) {'
  ],
  ['grandTotalBytes, differentialDownloader.options.onProgress);', 'grandTotalBytes, onProgress);'],
  [
    '                    response.pipe(out, {',
    '                    response.on("data", chunk => onProgress({ delta: chunk.length }));\n                    response.pipe(out, {'
  ],
  [
    `        response.on("end", () => {
            setTimeout(() => {
                request.abort();
                reject(new Error("Response ends without calling any handlers"));
            }, 10000);
        });`,
    `        // DataSplitter._final validates EOF; do not leave a delayed abort
        // attached to an already completed multipart request.
        response.on("error", reject);
        response.on("aborted", () => reject(new Error("Multipart response aborted")));`
  ],
  [
    'function checkIsRangesSupported(response, reject) {',
    `function watchCancellation(request, token, reject) {
    const cancel = () => {
        request.abort();
        reject(new builder_util_runtime_1.CancellationError());
    };
    // Electron can close the request's writable side while its response is
    // still streaming. Keep cancellation active until the response ends.
    const cleanup = () => token.removeListener("cancel", cancel);
    request.once("response", response => {
        response.once("end", cleanup);
        response.once("aborted", cleanup);
        response.once("error", cleanup);
    });
    request.once("error", cleanup);
    request.once("abort", cleanup);
    if (token.cancelled) cancel();
    else token.once("cancel", cancel);
}
function checkIsRangesSupported(response, reject) {`
  ]
])
await patch('DataSplitter', [
  [
    '            console.error(`Trailing ignored data: ${data.length} bytes`);\n            return;',
    '            callback(); // Multipart epilogues may arrive in a separate packet.\n            return;'
  ],
  [
    '    async handleData(chunk) {',
    `    _final(callback) {
        if (this.isFinished) { callback(); return; }
        // A response may end exactly at its final boundary. Completion must not
        // depend on receiving another TCP chunk after that boundary.
        const last = this.partIndexToLength.length - 1;
        if (this.partIndex !== last || this.remainingPartDataCount !== 0 ||
            this.actualPartLength !== this.partIndexToLength[last]) {
            callback(new Error("Incomplete multipart range response"));
            return;
        }
        this.copyExistingData(this.partIndexToTaskIndex.get(last) + 1, this.options.end)
            .then(() => {
                this.partIndex++;
                this.onPartEnd();
                this.finishHandler();
                callback();
            }).catch(callback);
    }
    async handleData(chunk) {`
  ],
  [
    `        const headerListEnd = chunk.indexOf(DOUBLE_CRLF, readOffset);`,
    `        const bufferedLength = this.headerListBuffer == null ? 0 : this.headerListBuffer.length;
        const headers = bufferedLength === 0 ? chunk.subarray(readOffset) :
            Buffer.concat([this.headerListBuffer, chunk.subarray(readOffset)]);
        const headerListEnd = headers.indexOf(DOUBLE_CRLF);`
  ],
  [
    '            return headerListEnd + DOUBLE_CRLF.length;',
    '            this.headerListBuffer = null;\n            return readOffset + headerListEnd + DOUBLE_CRLF.length - bufferedLength;'
  ]
])
console.log('Patched electron-updater: bounded ranges, multipart EOF/headers and cancellation')
