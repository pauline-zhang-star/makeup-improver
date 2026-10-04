const $ = (id) => document.getElementById(id);
const styles = [
  ['Auto', '✦'], ['Natural', '◌'], ['Work / Polished', '◇'],
  ['Korean Soft', '❋'], ['Fresh', '✳'], ['Date Night', '✧'],
  ['Sophisticated', '◆'], ['Soft Glam', '✺'],
];
const areaNames = {
  zh: {eyebrows:'眉毛', eyeliner:'眼线', lashes:'睫毛', eyeshadow:'眼影', nose_contour:'鼻部修饰', blush:'腮红', lips:'唇妆', complexion:'底妆'},
  en: {eyebrows:'Brows', eyeliner:'Eyeliner', lashes:'Lashes', eyeshadow:'Eyeshadow', nose_contour:'Nose contour', blush:'Blush', lips:'Lips', complexion:'Complexion'},
};
const translations = {
  zh: {
    brandAria:'Mirror 首页', topNote:'YOUR MAKEUP, REIMAGINED', local:'本机运行', publicLabel:'在线体验', eyebrow:'PERSONAL MAKEUP STUDIO',
    heroLine1:'看见更适合', heroLine2:'自己的', heroLine3:'妆容。',
    heroLede:'上传一张清晰自拍，选择喜欢的风格。我们会根据你现在的妆容，设计一张可以对照、可以跟着化的效果图。',
    point1:'保留你的样子', point2:'按原妆调整', point3:'逐步教你实现', aside:'YOUR LOOK, MORE YOU.',
    startKicker:'START HERE', yourPhoto:'你的照片', previewAlt:'待上传照片预览', upload:'点击或拖放自拍照', uploadLimit:'JPG / PNG / HEIC · 最大 12 MB', changePhoto:'更换照片', heicReady:'HEIC 已选择，可点击生成', heicDecode:'这张 HEIC 超过线上直接上传限制，且当前浏览器无法转换；请用 Safari 打开，或先导出为 JPG。',
    photoHint:'建议正面、光线均匀、眉眼和嘴唇清楚可见。若人脸太小或有明确黑边，会先在本机裁剪；点击生成后将工作图发送给 OpenAI API。',
    publicPhotoHint:'建议上传正面、光线均匀、眉眼和嘴唇清楚可见的照片。点击生成后，服务器会将工作图发送给 OpenAI API；照片和结果只作临时处理，约两小时后清除。',
    statelessPhotoHint:'照片仅在本次生成请求中临时处理，结果直接返回此页面；服务器不长期保存照片。过大的照片会在浏览器中先压缩；如果浏览器无法读取 HEIC，可直接上传不超过 3 MB 的 HEIC。',
    optional:'OPTIONAL', styleTitle:'想要的风格', styleIntro:'没有想法？保持「Auto」，让 AI 根据照片选择。', styleAria:'妆容风格', generate:'生成我的妆容',
    submitNote:'生成通常需要几分钟。上传质量不合格会在调用图片 API 前提示重拍。', resultKicker:'YOUR RESULT', resultTitle:'焕新的你',
    emptyTitle:'效果会在这里出现', emptyBody:'选择照片，开启一次为你设计的妆容体验。', preparing:'正在准备照片', progressInitial:'我们会先分析当前妆容，再生成效果图。',
    stepUpload:'照片检查', stepPlan:'选择技法', stepCreate:'生成图片', stepCompare:'核对变化',
    stageAria:'原图与生成图对比，点击照片或拖动分界线', beforeAlt:'原始照片', afterAlt:'生成的妆容照片', beforeTag:'原图', afterTag:'生成图', rangeAria:'拖动查看原图和妆容效果', compareHint:'点击照片任意位置，或按住拖动',
    detailsKicker:'THE DETAILS', guidanceTitle:'怎样化出这个妆', plannedTitle:'计划技法 · 尚未确认效果', auditTitle:'本次记录', auditOpen:'展开详情 ＋', auditClose:'收起详情 −', uploadedLink:'查看未裁剪的上传图 ↗', fullReview:'查看完整测试记录 ↗', footer:'为你设计 · 由你决定',
    styleAuto:['自动匹配','AI 根据照片选择'], styleNatural:['自然清透','轻盈日常'], styleWork:['通勤精致','干净利落'], styleKorean:['韩系柔和','柔雾与层次'], styleFresh:['元气清新','明亮有精神'], styleDate:['约会夜妆','更鲜明的妆感'], styleSophisticated:['知性高级','克制的轮廓'], styleGlam:['柔和华丽','柔焦光泽'],
    invalidFile:'请选择不超过 12 MB 的 JPG、PNG 或 HEIC 照片。', readFile:'无法读取这张照片。', badResponse:'本机服务返回了无法读取的内容。', unavailable:'本机服务暂时不可用。',
    progressUpload:'上传到本机服务，随后检查清晰度与人脸。', progressChecking:'正在核对生成效果', progressDrawing:'正在绘制你的妆容', progressAnalyzing:'正在分析照片',
    progressCheckDetail:'对照原图核查五官和实际妆容变化。', progressDrawDetail:(n)=>`已选择 ${n} 项技法，正在生成一张完整效果图。`, progressAnalyzeDetail:'先检查照片，再结合风格挑选合适的技法。',
    retryRead:'正在重试读取结果…', displayError:'结果已保存，但页面显示失败。请打开完整测试记录。', count:(n)=>`${n} 项`, guideFallback:'查看完整测试记录。', legacyGuide:'这份旧记录未保存中文指导；下方显示英文原文。',
    quota:(visitor,total)=>`匿名访客今日还可生成 ${visitor} 次；全站剩余 ${total} 次。每日 00:00 UTC 重置。`, visitorLimit:'今天的两次生成机会已用完，请明天再来。', dailyLimit:(limit)=>`今天全站的 ${limit} 次生成机会已用完，请明天再来。`, busy:'已有照片正在处理，请稍后再试；本次不计入次数。', resultExpired:'这次照片结果已过期并被清除。请上传新照片再试。',
    success:'已生成妆容，并根据原图与效果图的实际差异写出步骤。点击照片任意位置，或按住拖动对比。',
    reframing:(n)=>`模型返回图把人脸缩放了 ${n > 0 ? '+' : ''}${n}%，与原图不对齐。本次结果仅供诊断，不能作为最终妆容；这是生成结果的问题。`,
    diagnostic:'这张生成图未通过检查，仅供对照诊断，不是最终妆容。', visualOnly:'生成图没有可靠的可见妆容变化，因此没有编造操作指导。', noChange:'没有选出合格的改善技法，请试另一张照片或风格。', failed:'本次生成未完成。请查看测试记录。', cropNote:'已在本机裁剪输入构图；下方“原图”是送入模型的裁剪图。裁剪不能保证模型保持对齐。',
    basisStyle:'风格基础', basisPhoto:'照片特征', noSelected:'没有入选技法。', planUnavailable:'规划未完成，不能判断是否有适用技法。', modelNoProposals:'模型没有提出修改技法；请查看下方的保留决定。', allFiltered:'模型提出了技法，但全部未通过本地校验；请查看规则检查。', plannedAudit:'选中的技法与依据', lookDirectionAudit:'整体妆容方向', planningDecisionsAudit:'模型逐部位决定', preservedAudit:'决定保留的部位', proposeDecision:'提议修改', preserveDecision:'保留', planningFailureAudit:'规划失败诊断', rulesAudit:'规则检查', generateAudit:'生成与检查', qualityAudit:'照片质量', cropAudit:'本机裁剪', reframeAudit:'模型构图偏移', costAudit:'API 费用', sourceMessage:'原始错误详情', candidate:'候选项', failedCheck:'未通过校验', unknown:'未知', attempt:(n)=>`第 ${n} 次`, cropBox:'原图坐标中的范围', reason:'原因', faceScale:'返回图人脸缩放', reframeExplanation:'图片编辑遮罩仅提供生成指引；这次返回图没有保持原图构图。', costApprox:(n)=>`约 $${n} USD`, costKnown:(n)=>`已知约 $${n} USD（未包含无法计价的调用）`, costMissing:'费用尚未记录', sourceNote:'技术检查字段及原始错误保留记录时的语言。', inputRejected:'照片质量未通过检查，请更换一张清晰、正面的照片；本次不计入免费次数。具体原因见本次记录。',
  },
  en: {
    brandAria:'Mirror home', topNote:'YOUR MAKEUP, REIMAGINED', local:'Runs locally', publicLabel:'Online demo', eyebrow:'PERSONAL MAKEUP STUDIO',
    heroLine1:'Discover a look', heroLine2:'that feels', heroLine3:' like you.',
    heroLede:'Upload a clear selfie and choose a style if you like. We will build on your current makeup to create a result you can compare and recreate.',
    point1:'Keep your identity', point2:'Build on your makeup', point3:'Follow clear steps', aside:'YOUR LOOK, MORE YOU.',
    startKicker:'START HERE', yourPhoto:'Your photo', previewAlt:'Selected selfie preview', upload:'Click or drop a selfie', uploadLimit:'JPG / PNG / HEIC · Up to 12 MB', changePhoto:'Change photo', heicReady:'HEIC selected; ready to generate', heicDecode:'This HEIC exceeds the direct upload limit and this browser cannot convert it. Open in Safari or export it as JPG first.',
    photoHint:'Use a front-facing photo with even light and visible brows, eyes and lips. Small faces or clear black borders may be cropped locally. The working image is sent to the OpenAI API after you click Generate.',
    publicPhotoHint:'Use a front-facing photo with even light and visible brows, eyes and lips. After you click Generate, the server sends a working image to the OpenAI API. Photos and results are temporary and removed after about two hours.',
    statelessPhotoHint:'Photos are processed only during this request and the result returns to this page; the server does not retain them. Oversized photos are compressed in your browser. If your browser cannot read HEIC, it can upload HEIC files up to 3 MB directly.',
    optional:'OPTIONAL', styleTitle:'Choose a style', styleIntro:'Not sure? Leave it on Auto and let AI choose from the photo.', styleAria:'Makeup style', generate:'Generate my look',
    submitNote:'Generation can take a few minutes. Low-quality uploads are rejected before the image API call.', resultKicker:'YOUR RESULT', resultTitle:'Your refined look',
    emptyTitle:'Your result will appear here', emptyBody:'Choose a photo to start your personalized makeup look.', preparing:'Preparing your photo', progressInitial:'We will review your makeup, then generate your new look.',
    stepUpload:'Check photo', stepPlan:'Choose techniques', stepCreate:'Generate image', stepCompare:'Review changes',
    stageAria:'Before and after comparison; click the photo or drag the divider', beforeAlt:'Original photo', afterAlt:'Enhanced makeup photo', beforeTag:'BEFORE', afterTag:'AFTER', rangeAria:'Drag to compare original and enhanced photos', compareHint:'Click anywhere on the photo or drag to compare',
    detailsKicker:'THE DETAILS', guidanceTitle:'How to get this look', plannedTitle:'Planned techniques · result unverified', auditTitle:'Run details', auditOpen:'Show details ＋', auditClose:'Hide details −', uploadedLink:'View uncropped upload ↗', fullReview:'View full test record ↗', footer:'Designed for you · Decided by you',
    styleAuto:['Auto','AI chooses from your photo'], styleNatural:['Natural','Light everyday polish'], styleWork:['Work / Polished','Clean and refined'], styleKorean:['Korean Soft','Soft focus and layers'], styleFresh:['Fresh','Bright and lively'], styleDate:['Date Night','More defined makeup'], styleSophisticated:['Sophisticated','Balanced definition'], styleGlam:['Soft Glam','Soft-focus glow'],
    invalidFile:'Choose a JPG, PNG, or HEIC photo under 12 MB.', readFile:'Could not read this photo.', badResponse:'The local service returned unreadable content.', unavailable:'The local service is temporarily unavailable.',
    progressUpload:'Sending the photo to the local service, then checking clarity and face visibility.', progressChecking:'Reviewing the generated result', progressDrawing:'Creating your look', progressAnalyzing:'Analyzing your photo',
    progressCheckDetail:'Comparing facial features and visible makeup changes with the original.', progressDrawDetail:(n)=>`${n} techniques selected. Generating one complete image.`, progressAnalyzeDetail:'Checking the photo, then choosing techniques for the style.',
    retryRead:'Retrying the result…', displayError:'The result was saved, but the page could not show it. Open the full test record.', count:(n)=>`${n} steps`, guideFallback:'See the full test record.', legacyGuide:'This older result has no saved Chinese instructions; the English original is shown.',
    quota:(visitor,total)=>`Anonymous visitor: ${visitor} tries left today; ${total} left site-wide. Resets at 00:00 UTC.`, visitorLimit:'Your two tries for today are used up. Please return tomorrow.', dailyLimit:(limit)=>`The site-wide limit of ${limit} tries has been reached today. Please return tomorrow.`, busy:'Another photo is being processed. Try again shortly; this does not use a try.', resultExpired:'This photo result has expired and was removed. Upload a new photo to try again.',
    success:'Look generated. Steps describe the visible changes between the original and result. Click anywhere on the photo or drag to compare.',
    reframing:(n)=>`The model resized the face by ${n > 0 ? '+' : ''}${n}%, so it no longer aligns with the original. This is a diagnostic result, not a final look.`,
    diagnostic:'This generated image did not pass review. It is shown only for comparison, not as a final look.', visualOnly:'No reliable visible makeup change was found, so no steps were invented.', noChange:'No suitable improvements were selected. Try another photo or style.', failed:'This generation did not finish. See the test record.', cropNote:'The input was cropped locally. “Before” shows the working image sent to the model. Cropping cannot guarantee alignment.',
    basisStyle:'Style baseline', basisPhoto:'Photo evidence', noSelected:'No techniques selected.', planUnavailable:'Planning did not finish, so suitability is unknown.', modelNoProposals:'The model proposed no changes; see its preserve decisions below.', allFiltered:'The model proposed techniques, but local validation rejected all of them. See rule checks.', plannedAudit:'Selected techniques and basis', lookDirectionAudit:'Overall look direction', planningDecisionsAudit:'Model decisions by area', preservedAudit:'Areas kept unchanged', proposeDecision:'Proposed edit', preserveDecision:'Preserved', planningFailureAudit:'Planning failure details', rulesAudit:'Rule checks', generateAudit:'Generation and review', qualityAudit:'Photo quality', cropAudit:'Local crop', reframeAudit:'Model framing shift', costAudit:'API cost', sourceMessage:'Original error details', candidate:'Candidate', failedCheck:'Did not pass validation', unknown:'Unknown', attempt:(n)=>`Attempt ${n}`, cropBox:'Crop box in original coordinates', reason:'Reason', faceScale:'Returned face scale', reframeExplanation:'The edit mask guides the model; this result did not preserve the original framing.', costApprox:(n)=>`About $${n} USD`, costKnown:(n)=>`Known cost about $${n} USD (excludes unpriced calls)`, costMissing:'Cost not recorded', sourceNote:'Technical fields and original errors retain their recorded language.', inputRejected:'The photo did not pass the quality check. Try a clearer front-facing photo. This does not use a free try. See run details for the reason.',
  },
};
const styleKeys = {Auto:'styleAuto', Natural:'styleNatural', 'Work / Polished':'styleWork', 'Korean Soft':'styleKorean', Fresh:'styleFresh', 'Date Night':'styleDate', Sophisticated:'styleSophisticated', 'Soft Glam':'styleGlam'};
function savedLanguage() {
  const fromUrl = new URLSearchParams(location.search).get('lang');
  if (fromUrl === 'en' || fromUrl === 'zh') return fromUrl;
  try { return localStorage.getItem('mirror-language') === 'en' ? 'en' : 'zh'; }
  catch { return 'zh'; }
}
let language = savedLanguage();
function t(key, ...args) {
  const value = translations[language][key];
  return typeof value === 'function' ? value(...args) : value;
}
const terminal = new Set([
  'completed', 'completed_no_changes', 'completed_no_visible_changes',
  'instructions_unavailable', 'planning_rejected', 'failed', 'rejected', 'candidate_rejected',
]);
const state = {file: null, previewUrl: null, sentImageDataUrl: null, style: 'Auto', jobId: null, timer: null, dragging: false, lastJob: null, progressStarted: false, error: null, errorKey: null, quota: null};

function renderQuota() {
  show('quota-status', Boolean(state.quota?.limited));
  if (state.quota?.limited) $('quota-status').textContent = t('quota', state.quota.visitorRemaining, state.quota.dailyRemaining);
  document.querySelector('[data-i18n="local"]').textContent = t(state.quota?.limited ? 'publicLabel' : 'local');
  document.querySelector('[data-i18n="photoHint"]').textContent = t(
    state.quota?.mode === 'serverless' ? 'statelessPhotoHint' : state.quota?.limited ? 'publicPhotoHint' : 'photoHint');
}

async function refreshQuota() {
  try {
    const response = await fetch('/api/quota', {cache: 'no-store'});
    if (response.ok) state.quota = await response.json();
    renderQuota();
  } catch { /* The server enforces limits even if the display is unavailable. */ }
}

function applyLanguage() {
  document.documentElement.lang = language === 'zh' ? 'zh-CN' : 'en';
  document.querySelector('.brand').href = language === 'en' ? '/?lang=en' : '/';
  for (const node of document.querySelectorAll('[data-i18n]')) node.textContent = t(node.dataset.i18n);
  for (const node of document.querySelectorAll('[data-i18n-aria]')) node.setAttribute('aria-label', t(node.dataset.i18nAria));
  for (const node of document.querySelectorAll('[data-i18n-alt]')) node.alt = t(node.dataset.i18nAlt);
  for (const button of document.querySelectorAll('[data-language]')) button.setAttribute('aria-pressed', String(button.dataset.language === language));
  $('audit-toggle').textContent = t($('audit-body').hidden ? 'auditOpen' : 'auditClose');
  renderStyles();
  renderQuota();
  if (state.lastJob) {
    if (terminal.has(state.lastJob.status)) renderJob(state.lastJob, true);
    else progressFor(state.lastJob);
  } else if (state.progressStarted && !$('progress').hidden) {
    $('progress-title').textContent = t('preparing');
    $('progress-detail').textContent = t('progressUpload');
  } else if (state.error) setMessage(state.errorKey ? t(state.errorKey) : state.error, 'error');
}

function make(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = String(text);
  if (className) node.className = className;
  return node;
}

function show(id, visible) { $(id).hidden = !visible; }

function setMessage(message, kind = 'warning') {
  const banner = $('status-banner');
  banner.className = `status-banner ${kind}`;
  banner.textContent = message;
}

function renderStyles() {
  $('styles').replaceChildren();
  for (const [value, symbol] of styles) {
    const [label, detail] = t(styleKeys[value]);
    const button = make('button', null, 'style-option');
    button.type = 'button';
    button.setAttribute('role', 'radio');
    button.setAttribute('aria-checked', String(value === state.style));
    button.dataset.style = value;
    button.append(make('span', symbol, 'style-symbol'));
    const copy = make('span');
    copy.append(make('strong', label), make('small', detail));
    button.append(copy);
    button.addEventListener('click', () => {
      state.style = value;
      for (const option of $('styles').children) {
        option.setAttribute('aria-checked', String(option.dataset.style === value));
      }
    });
    $('styles').append(button);
  }
}

function isHeic(file) {
  return ['image/heic', 'image/heif'].includes(file.type.toLowerCase()) || /\.(heic|heif)$/i.test(file.name);
}

function chooseFile(file) {
  if (!file) return;
  if ((!['image/jpeg', 'image/png'].includes(file.type) && !isHeic(file)) || file.size > 12 * 1024 * 1024) {
    state.file = null;
    $('generate').disabled = true;
    state.lastJob = null;
    state.errorKey = 'invalidFile';
    show('outcome', true);
    show('empty-state', false);
    show('progress', false);
    show('comparison', false);
    show('guidance', false);
    show('audit', false);
    show('uploaded-link', false);
    show('full-review', false);
    state.error = t('invalidFile');
    setMessage(state.error, 'error');
    return;
  }
  state.file = file;
  if (state.previewUrl) URL.revokeObjectURL(state.previewUrl);
  state.previewUrl = URL.createObjectURL(file);
  $('upload-placeholder').querySelector('strong').textContent = t('upload');
  $('upload-placeholder').querySelector('small').textContent = t('uploadLimit');
  $('photo-preview').onerror = () => {
    if (state.file !== file || !isHeic(file)) return;
    show('photo-preview', false);
    $('upload-placeholder').querySelector('strong').textContent = file.name;
    $('upload-placeholder').querySelector('small').textContent = t('heicReady');
    show('upload-placeholder', true);
  };
  $('photo-preview').src = state.previewUrl;
  show('photo-preview', true);
  show('photo-action', true);
  show('upload-placeholder', false);
  $('generate').disabled = false;
}

function setupUpload() {
  $('photo-input').addEventListener('change', (event) => chooseFile(event.target.files[0]));
  const zone = $('dropzone');
  for (const name of ['dragenter', 'dragover']) {
    zone.addEventListener(name, (event) => { event.preventDefault(); zone.classList.add('dragging'); });
  }
  for (const name of ['dragleave', 'drop']) {
    zone.addEventListener(name, (event) => { event.preventDefault(); zone.classList.remove('dragging'); });
  }
  zone.addEventListener('drop', (event) => chooseFile(event.dataTransfer.files[0]));
}

function readBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(',', 2)[1]);
    reader.onerror = () => reject(new Error(t('readFile')));
    reader.readAsDataURL(file);
  });
}

async function prepareServerlessPhoto(file) {
  const heic = isHeic(file);
  let bitmap;
  try { bitmap = await createImageBitmap(file); }
  catch (error) {
    if (!heic || file.size > 3_000_000) throw new Error(t(heic ? 'heicDecode' : 'readFile'));
    return {image: await readBase64(file), preview: null};
  }
  try {
    if (!heic && file.size <= 2_500_000 && bitmap.width * bitmap.height <= 20_000_000) {
      const originalDataUrl = `data:${file.type};base64,${await readBase64(file)}`;
      return {image: originalDataUrl.split(',', 2)[1], preview: originalDataUrl};
    }
    const canvas = document.createElement('canvas');
    for (const maxEdge of [4000, 3200, 2600, 2100, 1700, 1300]) {
      const factor = Math.min(1, maxEdge / Math.max(bitmap.width, bitmap.height),
        Math.sqrt(20_000_000 / (bitmap.width * bitmap.height)));
      canvas.width = Math.max(1, Math.round(bitmap.width * factor));
      canvas.height = Math.max(1, Math.round(bitmap.height * factor));
      canvas.getContext('2d').drawImage(bitmap, 0, 0, canvas.width, canvas.height);
      for (const quality of [0.88, 0.8, 0.72]) {
        const preview = canvas.toDataURL('image/jpeg', quality);
        const image = preview.split(',', 2)[1];
        if (image.length < 3_300_000) return {image, preview};
      }
    }
    throw new Error(t('invalidFile'));
  } finally { bitmap.close(); }
}

async function clientBeforeUrl(job) {
  if (!state.sentImageDataUrl || !job.inputCrop?.cropBox) return state.sentImageDataUrl;
  const photo = new Image();
  photo.src = state.sentImageDataUrl;
  await photo.decode();
  const [x0, y0, x1, y1] = job.inputCrop.cropBox;
  const canvas = document.createElement('canvas');
  canvas.width = x1 - x0;
  canvas.height = y1 - y0;
  canvas.getContext('2d').drawImage(photo, x0, y0, canvas.width, canvas.height,
    0, 0, canvas.width, canvas.height);
  return canvas.toDataURL('image/jpeg', 0.9);
}

async function jsonResponse(response) {
  let body;
  try { body = await response.json(); } catch { throw new Error(t('badResponse')); }
  if (!response.ok) {
    const error = new Error(body.error || t('unavailable'));
    error.code = body.code;
    throw error;
  }
  return body;
}

function beginProgress() {
  state.lastJob = null;
  state.error = null;
  state.errorKey = null;
  state.progressStarted = true;
  show('empty-state', false);
  show('outcome', false);
  show('progress', true);
  $('generate').disabled = true;
  $('progress-title').textContent = t('preparing');
  $('progress-detail').textContent = t('progressUpload');
  $('progress-fill').style.width = '8%';
  for (const id of ['step-upload', 'step-plan', 'step-create', 'step-compare']) $(id).classList.remove('active');
  $('step-upload').classList.add('active');
  $('result-section').scrollIntoView({behavior: 'smooth', block: 'start'});
}

async function generate() {
  if (!state.file) return;
  clearTimeout(state.timer);
  beginProgress();
  try {
    if (!state.quota) await refreshQuota();
    if (!state.quota) throw new Error(t('unavailable'));
    if (state.quota.mode === 'serverless') {
      const prepared = await prepareServerlessPhoto(state.file);
      state.sentImageDataUrl = prepared.preview;
      $('progress-title').textContent = t('progressAnalyzing');
      $('progress-detail').textContent = t('progressAnalyzeDetail');
      $('progress-fill').style.width = '24%';
      const response = await fetch('/api/generate', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({style: state.style, image: prepared.image}),
      });
      const job = await jsonResponse(response);
      if (job.originalUrl === 'client:original') job.originalUrl = await clientBeforeUrl(job);
      renderJob(job);
      return;
    }
    const image = await readBase64(state.file);
    const response = await fetch('/api/jobs', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({style: state.style, image}),
    });
    const job = await jsonResponse(response);
    state.jobId = job.id;
    sessionStorage.setItem('mirror-job', job.id);
    const nextUrl = new URL(location.href);
    nextUrl.searchParams.set('job', job.id);
    history.replaceState(null, '', nextUrl);
    await pollJob();
  } catch (error) {
    renderError(error.code === 'VISITOR_LIMIT' ? t('visitorLimit') :
      error.code === 'DAILY_LIMIT' ? t('dailyLimit', state.quota?.dailyLimit ?? 50) :
        error.code === 'SERVER_BUSY' ? t('busy') : error.message);
  } finally { refreshQuota(); }
}

function renderError(message, key = null) {
  state.error = message;
  state.errorKey = key;
  clearTimeout(state.timer);
  show('progress', false);
  show('outcome', true);
  show('comparison', false);
  show('guidance', false);
  show('audit', false);
  show('uploaded-link', false);
  show('full-review', false);
  setMessage(message, 'error');
  $('generate').disabled = !state.file;
}

function progressFor(job) {
  const hasPlan = job.planned?.length > 0;
  const hasImage = Boolean(job.afterUrl);
  const stages = [true, hasPlan, hasPlan || hasImage, hasImage];
  ['step-upload', 'step-plan', 'step-create', 'step-compare'].forEach((id, index) =>
    $(id).classList.toggle('active', stages[index]));
  $('progress-fill').style.width = hasImage ? '91%' : hasPlan ? '57%' : '24%';
  $('progress-title').textContent = hasImage ? t('progressChecking') : hasPlan ? t('progressDrawing') : t('progressAnalyzing');
  $('progress-detail').textContent = hasImage
    ? t('progressCheckDetail')
    : hasPlan ? t('progressDrawDetail', job.planned.length)
      : t('progressAnalyzeDetail');
}

async function pollJob() {
  if (!state.jobId) return;
  let job;
  try {
    const response = await fetch(`/api/jobs/${state.jobId}`, {cache: 'no-store'});
    if (response.status === 410 || response.status === 404) {
      renderError(t('resultExpired'), 'resultExpired');
      sessionStorage.removeItem('mirror-job');
      state.jobId = null;
      return;
    }
    job = await jsonResponse(response);
    if (!state.file && styleKeys[job.style] && state.style !== job.style) {
      state.style = job.style;
      renderStyles();
    }
  } catch (error) {
    $('progress-detail').textContent = `${error.message} ${t('retryRead')}`;
    state.timer = setTimeout(pollJob, 4000);
    return;
  }
  if (terminal.has(job.status)) {
    clearTimeout(state.timer);
    try { renderJob(job); } catch {
      renderError(t('displayError'), 'displayError');
      show('full-review', Boolean(job.reviewUrl));
      if (job.reviewUrl) $('full-review').href = job.reviewUrl;
    }
    return;
  }
  state.lastJob = job;
  progressFor(job);
  state.timer = setTimeout(pollJob, 2200);
}

function splitAt(value) {
  const clamped = Math.max(0, Math.min(100, Number(value)));
  $('photo-stage').style.setProperty('--split', `${clamped}%`);
  $('compare-range').value = String(clamped);
}

function setupSlider() {
  const stage = $('photo-stage');
  const pointerSplit = (event) => {
    const rect = stage.getBoundingClientRect();
    splitAt(((event.clientX - rect.left) / rect.width) * 100);
  };
  stage.addEventListener('pointerdown', (event) => {
    state.dragging = true;
    stage.setPointerCapture(event.pointerId);
    pointerSplit(event);
  });
  stage.addEventListener('pointermove', (event) => { if (state.dragging) pointerSplit(event); });
  const end = () => { state.dragging = false; };
  stage.addEventListener('pointerup', end);
  stage.addEventListener('pointercancel', end);
  $('compare-range').addEventListener('input', (event) => splitAt(event.target.value));
  splitAt(50);
}

function renderCallouts(callouts) {
  const svg = $('annotation-lines');
  const badges = $('annotation-badges');
  svg.replaceChildren();
  badges.replaceChildren();
  svg.setAttribute('viewBox', '0 0 1000 1000');
  svg.setAttribute('preserveAspectRatio', 'none');
  const ns = 'http://www.w3.org/2000/svg';
  const defs = document.createElementNS(ns, 'defs');
  const marker = document.createElementNS(ns, 'marker');
  for (const [key, value] of Object.entries({id:'arrow-tip', viewBox:'0 0 10 10', refX:'9', refY:'5', markerWidth:'6', markerHeight:'6', orient:'auto'})) marker.setAttribute(key, value);
  const arrow = document.createElementNS(ns, 'path');
  arrow.setAttribute('d', 'M0 0 L10 5 L0 10 Z');
  arrow.setAttribute('fill', '#a75c66');
  marker.append(arrow);
  defs.append(marker);
  svg.append(defs);
  for (const item of callouts || []) {
    const [x, y] = item.label || [];
    const [x2, y2] = item.end || [];
    if (![x, y, x2, y2].every((value) => Number.isFinite(value) && value >= 0 && value <= 1)) continue;
    for (const halo of [true, false]) {
      const line = document.createElementNS(ns, 'line');
      for (const [key, value] of Object.entries({x1:x * 1000, y1:y * 1000, x2:x2 * 1000, y2:y2 * 1000})) line.setAttribute(key, String(value));
      line.setAttribute('stroke', halo ? '#fff' : '#a75c66');
      line.setAttribute('stroke-width', halo ? '5' : '2.2');
      line.setAttribute('stroke-dasharray', halo ? '0' : '9 7');
      if (!halo) line.setAttribute('marker-end', 'url(#arrow-tip)');
      svg.append(line);
    }
    const badge = make('span', item.number, 'annotation-badge');
    badge.style.left = `${x * 100}%`;
    badge.style.top = `${y * 100}%`;
    badges.append(badge);
  }
}

function renderGuides(job) {
  const observed = job.status === 'completed';
  const guides = observed ? job.steps || [] : job.plannedGuides || [];
  show('guidance', guides.length > 0);
  $('guidance-title').textContent = observed ? t('guidanceTitle') : t('plannedTitle');
  $('guide-count').textContent = t('count', guides.length);
  const legacy = language === 'zh' && guides.some((guide) => !guide.instruction_zh);
  show('legacy-guide-note', legacy);
  if (legacy) $('legacy-guide-note').textContent = t('legacyGuide');
  const list = $('guide-list');
  list.replaceChildren();
  for (const [index, guide] of guides.entries()) {
    const li = make('li');
    li.append(make('span', index + 1, 'guide-num'));
    const copy = make('div');
    copy.append(make('strong', areaNames[language][guide.area] || guide.area));
    copy.append(make('p', (language === 'zh' && guide.instruction_zh) || guide.instruction || t('guideFallback')));
    li.append(copy);
    list.append(li);
  }
}

function auditBlock(title, lines) {
  if (!lines.length) return;
  const block = make('section', null, 'audit-block');
  block.append(make('h4', title));
  for (const line of lines) block.append(make('p', line));
  $('audit-body').append(block);
}

function renderAudit(job) {
  $('audit-body').replaceChildren();
  const selected = (job.planned || []).map((item) => {
    const basis = item.basis === 'style_baseline' ? t('basisStyle') : t('basisPhoto');
    const evidence = (Array.isArray(item.evidence) ? item.evidence : [])
      .map((x) => x.feature ? `${x.feature}: ${x.measured_value}` : (x.observation || ''))
      .filter(Boolean).join('；');
    return `${item.id} · ${areaNames[language][item.area] || item.area} · ${basis}${evidence ? ` · ${evidence}` : ''}`;
  });
  const decisions = job.planningDecisions || [];
  const emptyPlan = !job.planAvailable ? t('planUnavailable')
    : (job.rejected || []).length ? t('allFiltered')
      : decisions.some((item) => item.kind === 'propose') ? t('noSelected') : t('modelNoProposals');
  auditBlock(t('plannedAudit'), selected.length ? selected : [emptyPlan]);
  if (job.lookDirection) auditBlock(t('lookDirectionAudit'), [job.lookDirection]);
  auditBlock(t('planningDecisionsAudit'), decisions.map((item) => {
    const area = areaNames[language][item.region] || item.region || t('unknown');
    return item.kind === 'preserve'
      ? `${area} · ${t('preserveDecision')}${item.reason ? ` · ${item.reason}` : ''}`
      : `${item.id || t('candidate')} · ${area} · ${t('proposeDecision')}`;
  }));
  auditBlock(t('preservedAudit'), (job.preserved || []).map((item) =>
    `${areaNames[language][item.region] || item.region} · ${item.reason || ''}`));
  auditBlock(t('rulesAudit'), (job.rejected || []).map((item) =>
    `${item.technique_id || item.id || t('candidate')}：${item.reason || item.rejection_reason || t('failedCheck')}`));
  if (job.planningFailure) auditBlock(t('planningFailureAudit'), [JSON.stringify(job.planningFailure)]);
  auditBlock(t('generateAudit'), (job.attempts || []).map((attempt, index) => {
    const checks = Object.entries(attempt.checks || {}).map(([name, status]) => `${name}: ${status}`).join('；');
    return `${t('attempt', index + 1)}：${attempt.status || t('unknown')}${attempt.message ? ` · ${attempt.message}` : ''}${checks ? ` · ${checks}` : ''}`;
  }));
  if (job.inputQuality) auditBlock(t('qualityAudit'), [job.inputQuality.message || JSON.stringify(job.inputQuality)]);
  if (job.inputCrop) {
    const box = job.inputCrop.cropBox || [];
    auditBlock(t('cropAudit'), [`${t('beforeTag')} ${job.inputCrop.sourceSize?.join(' × ')} → ${t('afterTag')} ${job.inputCrop.workingSize?.join(' × ')}`,
      `${t('cropBox')}：${box.join(', ')}`, `${t('reason')}：${(job.inputCrop.reasons || []).join('、')}`]);
  }
  if (job.providerReframing) auditBlock(t('reframeAudit'), [
    `${t('faceScale')}：${job.providerReframing.faceScaleChangePercent > 0 ? '+' : ''}${job.providerReframing.faceScaleChangePercent}%`,
    t('reframeExplanation'),
  ]);
  const cost = job.cost != null ? t('costApprox', Number(job.cost).toFixed(4)) :
    job.knownCost != null ? t('costKnown', Number(job.knownCost).toFixed(4)) : t('costMissing');
  auditBlock(t('costAudit'), [cost]);
  if (job.message) auditBlock(t('sourceMessage'), [job.message]);
  if (language === 'zh') $('audit-body').append(make('p', t('sourceNote'), 'audit-source-note'));
  show('audit', true);
}

function renderJob(job, preserveSlider = false) {
  state.lastJob = job;
  show('progress', false);
  show('empty-state', false);
  show('outcome', true);
  $('generate').disabled = !state.file;
  const hasPair = Boolean(job.originalUrl && job.afterUrl);
  const success = job.status === 'completed';
  const visualOnly = job.status === 'completed_no_visible_changes';
  const noChange = ['completed_no_changes', 'planning_rejected'].includes(job.status);
  let message, kind;
  if (job.inputRejected) {
    message = t('inputRejected');
    kind = 'warning';
  } else if (success) {
    message = t('success');
    kind = 'success';
  } else if (job.providerReframing) {
    message = t('reframing', job.providerReframing.faceScaleChangePercent);
    kind = 'warning';
  } else if (job.diagnostic) {
    message = t('diagnostic');
    kind = 'warning';
  } else if (visualOnly) {
    message = t('visualOnly');
    kind = 'warning';
  } else if (noChange) {
    message = t('noChange');
    kind = 'warning';
  } else {
    message = t('failed');
    kind = 'error';
  }
  if (job.inputCrop) message = `${t('cropNote')} ${message}`;
  setMessage(message, kind);
  show('comparison', hasPair);
  if (hasPair) {
    $('before-image').src = job.originalUrl;
    $('after-image').src = job.afterUrl;
    renderCallouts(job.callouts);
    if (!preserveSlider) splitAt(50);
  }
  renderGuides(job);
  renderAudit(job);
  show('uploaded-link', Boolean(job.uploadedUrl));
  if (job.uploadedUrl) $('uploaded-link').href = job.uploadedUrl;
  show('full-review', Boolean(job.reviewUrl));
  if (job.reviewUrl) $('full-review').href = job.reviewUrl;
}

$('generate').addEventListener('click', generate);
$('audit-toggle').addEventListener('click', () => {
  const open = $('audit-body').hidden;
  show('audit-body', open);
  $('audit-toggle').setAttribute('aria-expanded', String(open));
  $('audit-toggle').textContent = t(open ? 'auditClose' : 'auditOpen');
});
$('status-banner').setAttribute('aria-live', 'polite');
for (const button of document.querySelectorAll('[data-language]')) button.addEventListener('click', () => {
  if (language === button.dataset.language) return;
  language = button.dataset.language;
  try { localStorage.setItem('mirror-language', language); } catch { /* Storage may be unavailable. */ }
  const nextUrl = new URL(location.href);
  if (language === 'en') nextUrl.searchParams.set('lang', 'en');
  else nextUrl.searchParams.delete('lang');
  history.replaceState(null, '', nextUrl);
  applyLanguage();
});
applyLanguage();
refreshQuota();
setupUpload();
setupSlider();
const savedJob = new URLSearchParams(location.search).get('job') || sessionStorage.getItem('mirror-job');
if (savedJob && /^[0-9a-f]{32}$/.test(savedJob)) {
  refreshQuota().then(() => {
    if (state.quota?.mode === 'serverless') return;
    state.jobId = savedJob;
    beginProgress();
    pollJob();
  });
}
