/**
 * drive_ocr.gs -- Batch-automate the manual workflow:
 *   upload PNG to Drive -> "Open with Google Docs" (Drive OCR) -> copy out text
 *
 * Runs entirely inside your Google account (script.google.com). No API keys,
 * no gcloud, no Cloud Console project, no advanced services to enable --
 * it calls the Drive REST API with the script's own OAuth token.
 *
 * ── SETUP ────────────────────────────────────────────────────────────────
 * 1. Upload the page images to a Drive folder.
 *      e.g. drag _pages/ into Drive, or let Drive for Desktop sync it.
 * 2. Create a second, empty Drive folder for the OCR output.
 * 3. https://script.google.com -> New project -> paste this file over Code.gs.
 * 4. Fill in SRC_FOLDER_ID and OUT_FOLDER_ID below (the long id in the
 *    folder's URL: drive.google.com/drive/folders/<THIS_PART>).
 * 5. Project Settings (gear icon) -> tick "Show appsscript.json manifest
 *    file in editor". Open appsscript.json and add:
 *
 *      "oauthScopes": [
 *        "https://www.googleapis.com/auth/drive",
 *        "https://www.googleapis.com/auth/script.external_request",
 *        "https://www.googleapis.com/auth/script.scriptapp"
 *      ]
 *
 * 6. Run ocrOnePage() first to sanity-check one page + authorize.
 * 7. Then either:
 *      runOcrRange() -- pages RANGE_START..RANGE_END only, by page number
 *      runOcrBatch() -- every image in the source folder
 *    Both process until they near the 6-minute execution limit, then
 *    schedule themselves to continue automatically. Re-runs skip pages
 *    already done, so both are safe to run repeatedly.
 * 8. When done: right-click the output folder in Drive -> Download (zip),
 *    unzip into _pages_ocr/ next to _pages/.
 *
 * ── NOTES ────────────────────────────────────────────────────────────────
 * - Drive's OCR is the same engine as Cloud Vision, and is much better on
 *   Tamil than local Tesseract. It does NOT preserve two-column reading
 *   order reliably -- it usually reads straight across both columns. Check
 *   a couple of pages before trusting a whole tantra.
 * - Drive OCR degrades or fails on large images (roughly >2 MB). The
 *   _pages/*.png files are ~3.5 MB each. If pages come back empty or
 *   truncated, re-render them at lower DPI or as JPEG and re-upload;
 *   failures are listed in the run log and in _FAILED.txt.
 * - Each page costs one temporary Google Doc, deleted immediately after
 *   the text is exported.
 */

// ── CONFIG ───────────────────────────────────────────────────────────────

var SRC_FOLDER_ID = '1RIBJgsbT1CbQdeXu9f7zzD9fcF532of8';   // folder holding pg-###.png
var OUT_FOLDER_ID = '1kUcJTiymYaGdt_bMtqIcYVW69hHkdDpo';   // empty folder for .txt output

var OCR_LANGUAGE  = 'ta';        // ISO code hint: 'ta' Tamil, 'en' English
var MAX_RUNTIME_MS = 4.5 * 60 * 1000;  // stop before the 6-min hard limit
var TEST_PAGE     = 'pg-041.png';      // used by ocrOnePage()

var RANGE_START = 41;            // used by runOcrRange(), inclusive
var RANGE_END   = 60;            // used by runOcrRange(), inclusive

var CURSOR_KEY = 'DRIVE_OCR_CURSOR';
var TRIGGER_FN = 'runOcrBatch';
var RANGE_FN   = 'runOcrRange';

// ── ENTRY POINTS ─────────────────────────────────────────────────────────

/**
 * OCR a single named image, log the text, and write it to the output folder.
 * Use this to verify quality and to trigger the OAuth consent screen before
 * running the batch.
 */
function ocrOnePage() {
  var src = DriveApp.getFolderById(SRC_FOLDER_ID);
  var it = src.getFilesByName(TEST_PAGE);
  if (!it.hasNext()) throw new Error('Not found in source folder: ' + TEST_PAGE);

  var text = ocrImage_(it.next());
  Logger.log('--- %s (%s chars) ---\n%s', TEST_PAGE, text.length, text);

  var out = DriveApp.getFolderById(OUT_FOLDER_ID);
  var outName = TEST_PAGE.replace(/\.[^.]+$/, '') + '.txt';
  // Replace rather than accumulate, so repeated test runs stay clean.
  var existing = out.getFilesByName(outName);
  while (existing.hasNext()) existing.next().setTrashed(true);
  out.createFile(outName, text, MimeType.PLAIN_TEXT);
  Logger.log('wrote %s to output folder', outName);

  return text;
}

/**
 * Batch-process every image in the source folder. Resumable: keeps a Drive
 * iterator continuation token in script properties and re-schedules itself
 * when it runs out of execution time.
 */
function runOcrBatch() {
  var started = new Date().getTime();
  var props = PropertiesService.getScriptProperties();
  var out = DriveApp.getFolderById(OUT_FOLDER_ID);

  var token = props.getProperty(CURSOR_KEY);
  var files = token
    ? DriveApp.continueFileIterator(token)
    : DriveApp.getFolderById(SRC_FOLDER_ID).getFiles();

  var done = 0, skipped = 0, failed = [];

  while (files.hasNext()) {
    if (new Date().getTime() - started > MAX_RUNTIME_MS) {
      props.setProperty(CURSOR_KEY, files.getContinuationToken());
      scheduleContinuation_(TRIGGER_FN);
      Logger.log('Time limit reached. %s ocr\'d, %s skipped this run. ' +
                 'Continuing in ~1 min.', done, skipped);
      return;
    }

    var file = files.next();
    var name = file.getName();
    if (!/\.(png|jpe?g|gif|pdf)$/i.test(name)) continue;

    try {
      if (processPage_(file, out) === 'done') done++; else skipped++;
    } catch (err) {
      failed.push(name + ': ' + err.message);
      Logger.log('FAILED %s -- %s', name, err.message);
    }
  }

  // Iterator exhausted: the whole folder is processed.
  props.deleteProperty(CURSOR_KEY);
  clearTriggers_(TRIGGER_FN);
  if (failed.length) {
    out.createFile('_FAILED.txt', failed.join('\n'), MimeType.PLAIN_TEXT);
  }
  Logger.log('COMPLETE. %s ocr\'d, %s already present, %s failed.',
             done, skipped, failed.length);
}

/**
 * Process only pages RANGE_START..RANGE_END (inclusive), by page number
 * rather than by folder order. Needs no cursor to resume: pages whose .txt
 * already exists are skipped, so a continuation just re-walks the range and
 * picks up where it stopped.
 */
function runOcrRange() {
  var started = new Date().getTime();
  var src = DriveApp.getFolderById(SRC_FOLDER_ID);
  var out = DriveApp.getFolderById(OUT_FOLDER_ID);

  var done = 0, skipped = 0, missing = [], failed = [];

  for (var n = RANGE_START; n <= RANGE_END; n++) {
    if (new Date().getTime() - started > MAX_RUNTIME_MS) {
      scheduleContinuation_(RANGE_FN);
      Logger.log('Time limit reached at page %s. %s ocr\'d, %s already done. ' +
                 'Continuing in ~1 min.', n, done, skipped);
      return;
    }

    var file = findPage_(src, n);
    if (!file) { missing.push(n); continue; }

    try {
      if (processPage_(file, out) === 'done') done++; else skipped++;
    } catch (err) {
      failed.push(file.getName() + ': ' + err.message);
      Logger.log('FAILED %s -- %s', file.getName(), err.message);
    }
  }

  clearTriggers_(RANGE_FN);
  Logger.log('RANGE %s-%s COMPLETE. %s ocr\'d, %s already present, ' +
             '%s failed, %s not in folder.',
             RANGE_START, RANGE_END, done, skipped, failed.length,
             missing.length);
  if (missing.length) Logger.log('not in folder: %s', missing.join(', '));
  if (failed.length)  Logger.log('failures:\n%s', failed.join('\n'));
}

/** Forget the cursor and cancel pending continuations, to start over. */
function resetProgress() {
  PropertiesService.getScriptProperties().deleteProperty(CURSOR_KEY);
  clearTriggers_(TRIGGER_FN);
  clearTriggers_(RANGE_FN);
  Logger.log('Progress reset. Existing .txt files are still skipped; ' +
             'delete them from the output folder to force a re-OCR.');
}

// ── SHARED ───────────────────────────────────────────────────────────────

/** OCR one image into <name>.txt in the output folder. 'done' | 'skipped'. */
function processPage_(file, out) {
  var name = file.getName();
  var outName = name.replace(/\.[^.]+$/, '') + '.txt';
  if (out.getFilesByName(outName).hasNext()) return 'skipped';

  var text = ocrImage_(file);
  if (!text.replace(/\s/g, '')) throw new Error('OCR returned no text');
  out.createFile(outName, text, MimeType.PLAIN_TEXT);
  Logger.log('%s -> %s (%s chars)', name, outName, text.length);
  return 'done';
}

/** Find the image for a page number, tolerating 3-digit, 4-digit or bare. */
function findPage_(src, n) {
  var stems = ['pg-' + zeroPad_(n, 3), 'pg-' + zeroPad_(n, 4), 'pg-' + n];
  var exts  = ['.png', '.jpg', '.jpeg'];
  for (var i = 0; i < stems.length; i++) {
    for (var j = 0; j < exts.length; j++) {
      var it = src.getFilesByName(stems[i] + exts[j]);
      if (it.hasNext()) return it.next();
    }
  }
  return null;
}

function zeroPad_(n, width) {
  var s = String(n);
  while (s.length < width) s = '0' + s;
  return s;
}

// ── CORE ─────────────────────────────────────────────────────────────────

/**
 * The automated equivalent of "right-click -> Open with Google Docs":
 * upload the image asking Drive to convert it to a Doc (which runs OCR),
 * export that Doc as plain text, then delete the Doc.
 */
function ocrImage_(imageFile) {
  var docId = convertToDocWithOcr_(imageFile);
  try {
    return exportDocAsText_(docId);
  } finally {
    // Trash the temporary Doc even if the export failed.
    try { DriveApp.getFileById(docId).setTrashed(true); } catch (e) {}
  }
}

/**
 * Resumable upload of the image with target mimeType = Google Doc, which is
 * what makes Drive OCR it. Two requests (initiate, then send bytes) so we
 * never have to hand-assemble a multipart body. Returns the new Doc's id.
 *
 * Retries without the language hint in case this API version rejects it --
 * image-to-Doc conversion still OCRs, just with auto language detection.
 */
function convertToDocWithOcr_(imageFile) {
  try {
    return uploadAsDoc_(imageFile, true);
  } catch (err) {
    if (!/ocr/i.test(err.message)) throw err;
    return uploadAsDoc_(imageFile, false);
  }
}

function uploadAsDoc_(imageFile, withLanguageHint) {
  var blob = imageFile.getBlob();

  var url = 'https://www.googleapis.com/upload/drive/v3/files' +
            '?uploadType=resumable&supportsAllDrives=true';
  if (withLanguageHint) url += '&ocrLanguage=' + encodeURIComponent(OCR_LANGUAGE);

  var init = UrlFetchApp.fetch(url, {
    method: 'post',
    contentType: 'application/json; charset=UTF-8',
    headers: { Authorization: 'Bearer ' + ScriptApp.getOAuthToken() },
    payload: JSON.stringify({
      name: imageFile.getName(),
      mimeType: MimeType.GOOGLE_DOCS,   // <- asks Drive to convert, i.e. to OCR
      parents: [OUT_FOLDER_ID]
    }),
    muteHttpExceptions: true
  });
  if (init.getResponseCode() !== 200) {
    throw new Error('upload init ' + init.getResponseCode() + ': ' +
                    init.getContentText().slice(0, 300));
  }

  var headers = init.getAllHeaders();
  var session = headers['Location'] || headers['location'];
  if (!session) throw new Error('upload init returned no session URL');

  var put = UrlFetchApp.fetch(session, {
    method: 'put',
    contentType: blob.getContentType(),
    headers: { Authorization: 'Bearer ' + ScriptApp.getOAuthToken() },
    payload: blob.getBytes(),
    muteHttpExceptions: true
  });
  var code = put.getResponseCode();
  if (code !== 200 && code !== 201) {
    throw new Error('upload ' + code + ': ' +
                    put.getContentText().slice(0, 300));
  }

  return JSON.parse(put.getContentText()).id;
}

/** Export a Google Doc as UTF-8 plain text. */
function exportDocAsText_(fileId) {
  var url = 'https://www.googleapis.com/drive/v3/files/' + fileId +
            '/export?mimeType=text/plain';
  var res = UrlFetchApp.fetch(url, {
    headers: { Authorization: 'Bearer ' + ScriptApp.getOAuthToken() },
    muteHttpExceptions: true
  });
  if (res.getResponseCode() !== 200) {
    throw new Error('export ' + res.getResponseCode() + ': ' +
                    res.getContentText().slice(0, 200));
  }
  return res.getContentText('UTF-8').replace(/^﻿/, '');
}

// ── TRIGGERS ─────────────────────────────────────────────────────────────

function scheduleContinuation_(fnName) {
  clearTriggers_(fnName);
  ScriptApp.newTrigger(fnName).timeBased().after(60 * 1000).create();
}

function clearTriggers_(fnName) {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === fnName) ScriptApp.deleteTrigger(t);
  });
}
