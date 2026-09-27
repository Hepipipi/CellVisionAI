const state = { user: null, image: null, imageName: "", synthetic: false, latest: null, history: [], authMode: "login", currentView: "analysis", aiClasses: [], maskPolygons: [], maskDrawing: false, maskCurrent: [] };
const $ = (q) => document.querySelector(q);
const $$ = (q) => [...document.querySelectorAll(q)];

async function api(path, payload, method = "POST") {
  const response = await fetch(path, { method, headers: payload === undefined ? {} : { "Content-Type": "application/json" }, body: payload === undefined ? undefined : JSON.stringify(payload), credentials: "same-origin" });
  const type = response.headers.get("content-type") || "";
  const data = type.includes("json") ? await response.json() : await response.blob();
  if (!response.ok) throw new Error(data.error || `Ошибка ${response.status}`);
  return data;
}
function toast(message) { const el = $("#toast"); el.textContent = message; el.classList.add("show"); clearTimeout(toast.timer); toast.timer = setTimeout(() => el.classList.remove("show"), 3200); }
function showAuth(force = false) { $("#authOverlay").classList.toggle("visible", force); $("#openAuth").classList.toggle("hidden", !!state.user); $("#logoutBtn").classList.toggle("hidden", !state.user); }
function setUser(user) { state.user = user; $("#userName").textContent = user ? (user.first_name || user.username) : "Гость"; $("#profileUsername").textContent = user ? `@${user.username}` : "Войдите в аккаунт"; showAuth(); if (user) loadHistory(); }

function navigate(name) {
  if (!$("#view-" + name)) name = "analysis";
  state.currentView = name;
  $$(".view").forEach(el => el.classList.toggle("active", el.id === `view-${name}`));
  $$(".nav-link").forEach(el => el.classList.toggle("active", el.dataset.view === name));
  const titles = { analysis: ["Анализ снимка", "ЛАБОРАТОРИЯ"], comparison: ["Сравнение До / После", "МОНИТОРИНГ"], library: ["Атлас клеток", "СПРАВОЧНИК"], research: ["ИИ и протокол", "ИССЛЕДОВАНИЕ"], hospitals: ["Гематология в Бишкеке", "МАРШРУТ ПОМОЩИ"], profile: ["Профиль и история", "ЛИЧНЫЙ КАБИНЕТ"] };
  $("#pageTitle").textContent = titles[name][0]; $("#crumb").textContent = titles[name][1];
  if (name === "comparison" || name === "profile") loadHistory();
  if (location.hash !== `#${name}`) history.replaceState(null, "", `#${name}`);
}
$$('[data-view]').forEach(btn => btn.addEventListener("click", () => navigate(btn.dataset.view)));
$$('[data-goto]').forEach(btn => btn.addEventListener("click", () => navigate(btn.dataset.goto)));
window.addEventListener("hashchange", () => navigate(location.hash.slice(1)));

$("#authToggle").addEventListener("click", () => {
  state.authMode = state.authMode === "login" ? "register" : "login";
  const registration = state.authMode === "register";
  $("#authTitle").textContent = registration ? "Создайте рабочее пространство" : "Войдите в рабочее пространство";
  $("#authSubmit").textContent = registration ? "Создать аккаунт →" : "Войти →";
  $("#authToggle").innerHTML = registration ? "Уже есть аккаунт? <b>Войти</b>" : "Нет аккаунта? <b>Создать его</b>";
  $("#authPassword").autocomplete = registration ? "new-password" : "current-password";
});
$("#authForm").addEventListener("submit", async e => {
  e.preventDefault(); $("#authError").textContent = "";
  const path = state.authMode === "register" ? "/api/register" : "/api/login";
  try { const data = await api(path, { username: $("#authUsername").value.trim(), password: $("#authPassword").value }); setUser(data.user); toast("Вы вошли в систему"); }
  catch (error) { $("#authError").textContent = error.message; }
});
$("#openAuth").addEventListener("click", () => showAuth(true));
$("#logoutBtn").addEventListener("click", async () => { try { await api("/api/logout", {}); } catch (_) {} setUser(null); toast("Вы вышли из аккаунта"); });

function loadFile(file) {
  if (!file) return;
  if (!file.type.startsWith("image/")) return toast("Выберите файл изображения");
  if (file.size > 12 * 1024 * 1024) return toast("Максимальный размер снимка — 12 МБ");
  const reader = new FileReader();
  reader.onload = () => { setImage(reader.result, file.name, false); };
  reader.readAsDataURL(file);
}
function setImage(data, name, synthetic) {
  state.image = data; state.imageName = name; state.synthetic = synthetic;
  const img = new Image(); img.onload = () => { $("#previewImage").src = data; $("#imageName").textContent = name; $("#imageDimensions").textContent = `${img.naturalWidth} × ${img.naturalHeight} px`; $("#previewWrap").classList.remove("hidden"); $("#analyzeBtn").disabled = false; resetResults(); };
  img.src = data;
}
function resetResults() { state.latest = null; $("#resultContent").classList.add("hidden"); $("#emptyResults").classList.remove("hidden"); $("#resultStatus").textContent = "ОЖИДАНИЕ"; $("#resultStatus").className = "status-pill"; }
$("#fileInput").addEventListener("change", e => loadFile(e.target.files[0]));
$("#dropzone").addEventListener("click", e => { if (e.target.tagName !== "INPUT") $("#fileInput").click(); });
$("#dropzone").addEventListener("dragover", e => { e.preventDefault(); $("#dropzone").classList.add("dragover"); });
$("#dropzone").addEventListener("dragleave", () => $("#dropzone").classList.remove("dragover"));
$("#dropzone").addEventListener("drop", e => { e.preventDefault(); $("#dropzone").classList.remove("dragover"); loadFile(e.dataTransfer.files[0]); });
$("#removeImage").addEventListener("click", () => { state.image = null; $("#previewWrap").classList.add("hidden"); $("#analyzeBtn").disabled = true; resetResults(); });
$("#population").addEventListener("change", () => $("#trimesterField").classList.toggle("hidden", $("#population").value !== "pregnant"));
let cbcReportImage = null;
$("#cbcReportInput").addEventListener("change", e => {
  const file=e.target.files[0]; cbcReportImage=null; $("#cbcOcrStatus").textContent="";
  if(!file) return;
  if(!file.type.startsWith("image/")) { e.target.value=""; return toast("Выберите фотографию или скан бланка"); }
  if(file.size>12*1024*1024) { e.target.value=""; return toast("Максимальный размер файла — 12 МБ"); }
  const reader=new FileReader(); reader.onload=()=>{cbcReportImage=reader.result; $("#cbcOcrStatus").textContent=`Выбран файл: ${file.name}. Нажмите «Распознать показатели».`;}; reader.readAsDataURL(file);
});
$("#cbcOcrBtn").addEventListener("click", async()=>{
  if(!state.user) return showAuth(true);
  if(!cbcReportImage) return toast("Сначала выберите фотографию бланка");
  const button=$("#cbcOcrBtn"); button.disabled=true; button.textContent="Распознавание…"; $("#cbcOcrStatus").textContent="Читаем текст бланка…";
  try {
    const result=await api("/api/ocr/cbc",{image:cbcReportImage});
    $("#cbcOcrText").textContent=result.text||"Текст не распознан";
    const ids={hemoglobin:"hemoglobin",mcv:"mcv",mch:"mch",mchc:"mchc",rdw:"rdw",rbc:"rbc",hematocrit:"hematocrit"};
    Object.entries(ids).forEach(([key,id])=>{if(result.values?.[key]!=null) $(`#${id}`).value=result.values[key];});
    const got=Object.keys(result.values||{}).map(key=>`${key.toUpperCase()}: ${result.values[key]}`).join(" · ");
    $("#cbcOcrStatus").textContent=got?`${result.notice} Распознано: ${got}`:`${result.notice} Показатели автоматически не найдены — внесите Hb и другие значения вручную.`;
    toast("Распознавание завершено; сверьте значения с бланком");
  } catch(error) { $("#cbcOcrStatus").textContent=error.message; }
  finally { button.disabled=false; button.textContent="Распознать показатели"; }
});
$("#assessCbcBtn").addEventListener("click", async()=>{
  if(!state.user) return showAuth(true);
  const button=$("#assessCbcBtn"); button.disabled=true; button.textContent="Оцениваем…";
  try {
    const cbc=Object.fromEntries(["mcv","mch","mchc","rdw","rbc","hematocrit"].map(id=>[id,$(`#${id}`).value||null]));
    const result=await api("/api/assess-cbc",{hemoglobin:$("#hemoglobin").value||null,cbc,population:$("#population").value,trimester:Number($("#trimester").value),age:state.user.age||null});
    const box=$("#cbcOnlyResult"); box.replaceChildren(); box.classList.remove("hidden");
    const heading=document.createElement("h3"); heading.textContent=result.label; box.append(heading);
    const detail=document.createElement("p"); detail.textContent=result.detail; box.append(detail);
    const pattern=document.createElement("p"); pattern.textContent=`Индексы эритроцитов: ${result.cbc_patterns?.text||"недостаточно данных"} ${result.cbc_patterns?.note||""}`; box.append(pattern);
    const warning=document.createElement("small"); warning.textContent=result.notice; box.append(warning);
  } catch(error) { toast(error.message); }
  finally { button.disabled=false; button.textContent="Оценить лабораторный бланк"; }
});
$("#sampleBtn").addEventListener("click", async () => {
  $("#sampleBtn").disabled = true; $("#sampleBtn").textContent = "Создание…";
  try { const data = await api("/api/sample", { kind: $("#sampleKind").value }); setImage(data.image, data.filename, true); toast("Учебная схема создана"); }
  catch (error) { toast(error.message); }
  finally { $("#sampleBtn").disabled = false; $("#sampleBtn").textContent = "Создать"; }
});

$("#analyzeBtn").addEventListener("click", async () => {
  if (!state.user) return showAuth(true);
  if (!state.image) return toast("Сначала добавьте снимок");
  const button = $("#analyzeBtn"); button.disabled = true; button.innerHTML = '<span class="spinner"></span> Обработка снимка…';
  try {
    const rawHb = $("#hemoglobin").value;
    const px = Number($("#barPixels").value), um = Number($("#barMicrons").value);
    const pixelUm = px > 0 && um > 0 ? um / px : null;
    const cbc = Object.fromEntries(["mcv","mch","mchc","rdw","rbc","hematocrit"].map(id=>[id,$(`#${id}`).value||null]));
    const result = await api("/api/analyze", { image: state.image, filename: state.imageName, synthetic: state.synthetic,
      hemoglobin: rawHb ? Number(rawHb) : null, cbc, population: $("#population").value, trimester: Number($("#trimester").value), age: state.user.age || null, pixel_um: pixelUm });
    state.latest = result; renderResult(result); loadHistory(); toast("Анализ завершён и добавлен в историю");
  } catch (error) { toast(error.message); }
  finally { button.disabled = !state.image; button.innerHTML = 'Запустить исследовательский анализ <span>→</span>'; }
});

function renderResult(result) {
  $("#emptyResults").classList.add("hidden"); $("#resultContent").classList.remove("hidden");
  const assessment = result.assessment;
  const card = $("#assessmentCard"); card.className = `assessment-card ${assessment.status}`;
  $("#assessmentIcon").textContent = assessment.status === "below_cutoff" ? "!" : assessment.status === "not_below_cutoff" ? "✓" : "i";
  $("#assessmentTitle").textContent = assessment.label; $("#assessmentText").textContent = assessment.detail;
  const photo=result.image_screen||{};$("#imageScreenText").textContent=photo.detail||"Фото мазка используется для визуализации морфологии; вероятность анемии по снимку не выводится.";
  $("#morphologySummary").textContent=result.morphology_summary?.text||"";
  $("#cbcPatternText").textContent=`CBC-паттерн: ${result.cbc_patterns?.text||"индексы не введены"} ${result.cbc_patterns?.note||""}`;
  $("#inputResultImage").src = result.image_data; $("#segmentedImage").src = result.segmented_data;
  $("#resultStatus").textContent = result.cells.length ? `${result.cells.length} ОБЪЕКТОВ` : "НЕТ ОБЪЕКТОВ";
  $("#resultStatus").className = "status-pill done";
  const metrics = result.metrics || {};
  const calibrated = Number.isFinite(metrics.pixel_um);
  const stats = [["Сегментировано", metrics.cell_count ?? 0, "объектов"], ["Средняя площадь", metrics.mean_area ?? "—", "px²"], ["Медиана площади", metrics.median_area ?? "—", "px²"], ["Разброс размеров", metrics.cv_percent ?? "—", "% CV*"], ["Эквивалентный диаметр", metrics.mean_diameter ?? "—", "px"], ...(calibrated ? [["Масштабный диаметр", (metrics.mean_diameter * metrics.pixel_um).toFixed(2), "µm"]] : []), ["Круглость", metrics.mean_circularity ?? "—", "0–1"], ["Эксцентриситет", metrics.mean_eccentricity ?? "—", "0–1"], ["1-й квартиль площади", metrics.q1_area ?? "—", "px²"], ["3-й квартиль площади", metrics.q3_area ?? "—", "px²"]];
  $("#metricGrid").innerHTML = stats.map(([name, value, unit]) => `<div class="metric-card"><small>${name}</small><b>${value}</b><span>${unit}</span></div>`).join("");
  const q = result.quality || {};
  $("#qualityCard").innerHTML = `<b>Качество снимка · автоматические ориентиры</b><div class="quality-metrics"><span>Резкость <b>${q.focus_score ?? "—"}</b></span><span>Яркость <b>${q.mean_brightness ?? "—"}/255</b></span><span>Клиппинг <b>${q.clipped_percent ?? "—"}%</b></span><span>Разброс света <b>${q.illumination_spread ?? "—"}</b></span><span>Плотность поля <b>${q.dark_pixel_percent ?? "—"}%</b></span><span>Мелкие детали <b>${q.small_detail_percent ?? "—"}%</b></span></div><p>${(q.checks?.length ? q.checks.join(" · ") : "Явных проблем по заданным эвристикам не найдено")}. ${q.note || ""}</p>${q.retake_tips?.length?`<div class="retake-tips"><b>Что проверить перед пересъёмкой</b><ul>${q.retake_tips.map(x=>`<li>${escapeHtml(x)}</li>`).join("")}</ul></div>`:""}`;
  $("#aiStatus").textContent = result.ai?.message || (result.ai?.status === "trained" ? "Модель обучена; показаны исследовательские классы, не диагноз." : "Не обучен: нужны экспертно размеченные клетки.");
  renderAnnotations(result);
  renderMaskReview(result);
  drawHistogram(result.cells.map(c => c.area_px2));
  $("#cleanComparison").classList.add("hidden");
}
const labelOptions = ["не размечено","нормоцит","микроцит","макроцит","сфероцит","мишеневидная клетка","шистоцит / фрагмент","серповидная форма","овалоцит","другая форма","артефакт / пыль","не эритроцит"];
function renderAnnotations(result) {
  const image = new Image(); image.onload = () => {
    const sx=image.naturalWidth/(result.quality?.width||image.naturalWidth), sy=image.naturalHeight/(result.quality?.height||image.naturalHeight);
    const rows = result.cells.slice(0, 160).map(c => {
      const side = Math.max(c.bbox_width*sx, c.bbox_height*sy, 1), canvas = document.createElement("canvas"); canvas.width = canvas.height = 56;
      const ctx = canvas.getContext("2d"), x = Math.max(0, c.centroid_x*sx - side / 2), y = Math.max(0, c.centroid_y*sy - side / 2);
      ctx.fillStyle = "#f2f3f2"; ctx.fillRect(0,0,56,56); ctx.drawImage(image, x,y,side,side,0,0,56,56);
      const options=[...new Set([...labelOptions,...state.aiClasses])], selected = options.includes(c.ai_class) ? c.ai_class : "не размечено";
      return `<div class="annotation-row"><img src="${canvas.toDataURL("image/jpeg",.7)}" alt="Фрагмент клетки ${c.cell_number}"><b>#${c.cell_number}</b><span>${c.ai_class ? `ИИ: ${escapeHtml(c.ai_class)}` : "ИИ: нет метки"}</span><select data-cell="${c.cell_number}">${options.map(l=>`<option ${l===selected?"selected":""}>${escapeHtml(l)}</option>`).join("")}</select></div>`;
    }).join("");
    $("#annotationTable").innerHTML = rows || "<p>Нет сегментированных объектов для разметки.</p>";
    api(`/api/annotations?analysis_id=${result.id}`,undefined,"GET").then(data=>{const saved=new Map(data.items.map(x=>[x.cell_number,x.label]));$$("#annotationTable select").forEach(el=>{const label=saved.get(Number(el.dataset.cell));if(label&&[...el.options].some(o=>o.value===label))el.value=label;});}).catch(()=>{});
    renderIndependentReviews(result);
  }; image.src = result.image_data;
}
function renderIndependentReviews(result) {
  const entries=result.cells.slice(0,160), options=[...new Set([...labelOptions,...state.aiClasses])];
  $("#independentTable").innerHTML=entries.map(c=>`<div class="independent-row"><img data-review-crop="${c.cell_number}" alt="Фрагмент клетки ${c.cell_number}"><b>#${c.cell_number}</b><select data-review="A" data-cell="${c.cell_number}" aria-label="Метка наблюдателя A для клетки ${c.cell_number}">${options.map(x=>`<option>${escapeHtml(x)}</option>`).join("")}</select><select data-review="B" data-cell="${c.cell_number}" aria-label="Метка наблюдателя B для клетки ${c.cell_number}">${options.map(x=>`<option>${escapeHtml(x)}</option>`).join("")}</select><span data-agreement="${c.cell_number}">—</span></div>`).join("")||"<p>Нет объектов для сравнения.</p>";
  const image=new Image();image.onload=()=>{const sx=image.naturalWidth/(result.quality?.width||image.naturalWidth),sy=image.naturalHeight/(result.quality?.height||image.naturalHeight);for(const c of entries){const side=Math.max(c.bbox_width*sx,c.bbox_height*sy,1),canvas=document.createElement("canvas");canvas.width=canvas.height=48;const ctx=canvas.getContext("2d");ctx.fillStyle="#f2f3f2";ctx.fillRect(0,0,48,48);ctx.drawImage(image,Math.max(0,c.centroid_x*sx-side/2),Math.max(0,c.centroid_y*sy-side/2),side,side,0,0,48,48);const img=$(`#independentTable [data-review-crop="${c.cell_number}"]`);if(img)img.src=canvas.toDataURL("image/jpeg",.7);}};image.src=result.image_data;
  if(!result.id)return;
  api(`/api/annotations/independent?analysis_id=${result.id}`,undefined,"GET").then(d=>{
    $("#reviewerA").value=d.reviewers.find(x=>x.slot==="A")?.name||"";$("#reviewerB").value=d.reviewers.find(x=>x.slot==="B")?.name||"";
    const slots={A:{},B:{}};d.items.forEach(x=>{slots.A[x.cell_number]=x.a;slots.B[x.cell_number]=x.b;});
    $$("#independentTable select").forEach(el=>{const v=slots[el.dataset.review][el.dataset.cell];if(v&&[...el.options].some(o=>o.value===v))el.value=v;});
    showIndependentResult(d);
  }).catch(()=>{});
}
function showIndependentResult(data){$$("#independentTable [data-agreement]").forEach(el=>el.textContent="—");data.items?.forEach(x=>{const el=$(`#independentTable [data-agreement="${x.cell_number}"]`);if(el)el.textContent=x.agree?"Совпало":"Различается";});$("#independentResult").textContent=data.n?`Совпадение меток: ${(data.agreement*100).toFixed(1)}% · Cohen κ ${data.kappa??"—"} · общих клеток: ${data.n}. Показатель зависит от выбранных категорий и не является доказательством точности.`:"Нужно сохранить метки обоих наблюдателей для одних и тех же клеток.";}
function renderMaskReview(result, polygons) {
  const canvas=$("#maskCanvas"),ctx=canvas.getContext("2d"),base=new Image(),mask=new Image();
  state.maskPolygons=polygons||result.polygons||JSON.parse(result.expert_mask_json||"[]");
  const paint=()=>{
    if(!base.complete||!mask.complete||!base.naturalWidth||!mask.naturalWidth)return;
    canvas.width=base.naturalWidth;canvas.height=base.naturalHeight;ctx.clearRect(0,0,canvas.width,canvas.height);ctx.drawImage(base,0,0,canvas.width,canvas.height);
    const overlay=document.createElement("canvas");overlay.width=canvas.width;overlay.height=canvas.height;const ox=overlay.getContext("2d");ox.drawImage(mask,0,0,overlay.width,overlay.height);const pixels=ox.getImageData(0,0,overlay.width,overlay.height);for(let i=0;i<pixels.data.length;i+=4){if(pixels.data[i]>0){pixels.data[i]=32;pixels.data[i+1]=185;pixels.data[i+2]=113;pixels.data[i+3]=86;}}ox.putImageData(pixels,0,0);ctx.drawImage(overlay,0,0);
    const drawPoly=pts=>{if(pts.length<2)return;ctx.beginPath();ctx.moveTo(pts[0][0],pts[0][1]);pts.slice(1).forEach(p=>ctx.lineTo(p[0],p[1]));ctx.closePath();ctx.fillStyle="rgba(226,76,82,.20)";ctx.strokeStyle="#dd4f53";ctx.lineWidth=Math.max(2,canvas.width/500);ctx.fill();ctx.stroke();};state.maskPolygons.forEach(drawPoly);drawPoly(state.maskCurrent);
  };
  base.onload=paint;mask.onload=paint;base.src=result.image_data;mask.src=result.segmentation_mask_data||result.segmentation_mask||"";
  $("#maskMetric").textContent=state.maskPolygons.length?`${state.maskPolygons.length} ручных контуров сохранено`:"нет эталонных контуров";
  if(result.id)api(`/api/masks?analysis_id=${result.id}`,undefined,"GET").then(d=>{if(state.latest?.id!==result.id)return;state.maskPolygons=d.polygons||[];if(d.reviewer&&!$("#reviewerName").value)$("#reviewerName").value=d.reviewer;$("#maskMetric").textContent=d.evaluation?`Dice ${d.evaluation.dice} · IoU ${d.evaluation.iou}`:state.maskPolygons.length?`${state.maskPolygons.length} ручных контуров сохранено`:"нет эталонных контуров";paint();}).catch(()=>{});
  state.redrawMask=paint;
}
function canvasPoint(e){const c=$("#maskCanvas"),r=c.getBoundingClientRect();return[(e.clientX-r.left)*c.width/r.width,(e.clientY-r.top)*c.height/r.height];}
$("#maskCanvas").addEventListener("pointerdown",e=>{if(!state.maskDrawing)return;e.preventDefault();$("#maskCanvas").setPointerCapture(e.pointerId);state.maskCurrent=[canvasPoint(e)];state.redrawMask?.();});
$("#maskCanvas").addEventListener("pointermove",e=>{if(!state.maskDrawing||!state.maskCurrent.length)return;state.maskCurrent.push(canvasPoint(e));state.redrawMask?.();});
$("#maskCanvas").addEventListener("pointerup",()=>{if(state.maskCurrent.length>=4)state.maskPolygons.push(state.maskCurrent);state.maskCurrent=[];state.redrawMask?.();$("#maskMetric").textContent=`${state.maskPolygons.length} контуров · unsaved`;});
$("#drawMaskBtn").addEventListener("click",()=>{state.maskDrawing=!state.maskDrawing;$("#drawMaskBtn").classList.toggle("active",state.maskDrawing);$("#drawMaskBtn").textContent=state.maskDrawing?"Разметка включена · завершить":"Начать разметку";});
$("#clearMaskBtn").addEventListener("click",()=>{state.maskPolygons=[];state.maskCurrent=[];$("#maskMetric").textContent="контуры очищены · не сохранено";state.redrawMask?.();});
$("#saveMaskBtn").addEventListener("click",async()=>{if(!state.latest)return toast("Сначала выполните анализ");if(!state.maskPolygons.length)return toast("Сначала обведите область вручную");try{const r=await api("/api/annotations/mask",{analysis_id:state.latest.id,polygons:state.maskPolygons,reviewer:$("#reviewerName").value});$("#maskMetric").textContent=`Dice ${r.evaluation.dice} · IoU ${r.evaluation.iou} · ${r.evaluation.contours} контуров`;toast("Ручная маска сохранена; метрики относятся только к этому кадру.");}catch(e){toast(e.message);}});
$("#saveAnnotations").addEventListener("click", async () => {
  if (!state.latest) return;
  const labels = $$("#annotationTable select").map(el=>({cell_number:Number(el.dataset.cell),label:el.value}));
  try { const r=await api("/api/annotations",{analysis_id:state.latest.id,reviewer:$("#reviewerName").value,labels}); const ev=r.evaluation; $("#annotationStatus").textContent=`Сохранено меток: ${r.labels}${ev?.accuracy!=null?` · совпадение ${ev.accuracy*100}% (n=${ev.n})`:""}`; toast("Экспертные метки сохранены"); }
  catch(e){toast(e.message);}
});
$("#saveIndependent").addEventListener("click",async()=>{if(!state.latest?.id)return toast("Сохраните анализ снимка перед разметкой");try{for(const slot of ["A","B"]){const labels={};$$( `#independentTable select[data-review="${slot}"]`).forEach(el=>{if(el.value!=="не размечено")labels[el.dataset.cell]=el.value;});await api("/api/annotations/independent",{analysis_id:state.latest.id,reviewer_slot:slot,reviewer_name:$("#reviewer"+slot).value,labels});}const r=await api(`/api/annotations/independent?analysis_id=${state.latest.id}`,undefined,"GET");showIndependentResult(r);toast("Обе разметки сохранены");}catch(e){toast(e.message);}});
function updateCalibrationHint(){const px=Number($("#barPixels").value),um=Number($("#barMicrons").value);$("#calibrationResult").textContent=px>0&&um>0?`Калибровка: ${(um/px).toFixed(5)} µm/px` : "Без значений измерения остаются в пикселях.";}
["#barPixels","#barMicrons"].forEach(id=>$(id).addEventListener("input",updateCalibrationHint));
function drawHistogram(values) {
  const canvas = $("#histogram"), ctx = canvas.getContext("2d"), dpr = window.devicePixelRatio || 1;
  const width = Math.max(240, canvas.parentElement.clientWidth - 28), height = 132;
  canvas.width = width * dpr; canvas.height = height * dpr; canvas.style.width = `${width}px`; canvas.style.height = `${height}px`; ctx.scale(dpr, dpr); ctx.clearRect(0, 0, width, height);
  if (!values.length) { ctx.fillStyle = "#7a8790"; ctx.fillText("Объекты не сегментированы", 10, 26); return; }
  const min = Math.min(...values), max = Math.max(...values), bins = new Array(12).fill(0);
  values.forEach(v => bins[Math.min(11, Math.floor((v - min) / (max - min || 1) * 12))]++);
  const plotH = 88, maxCount = Math.max(...bins, 1), gap = 7, barW = (width - 38 - 11 * gap) / 12;
  bins.forEach((n, i) => { const bh = n / maxCount * plotH; ctx.fillStyle = "#588b7c"; ctx.beginPath(); ctx.roundRect(19 + i * (barW + gap), plotH - bh + 4, barW, bh, 3); ctx.fill(); });
  ctx.fillStyle = "#87938e"; ctx.font = "11px Inter, sans-serif"; ctx.fillText(`${min.toFixed(0)} px²`, 18, 115); ctx.fillText(`${max.toFixed(0)} px²`, width - 67, 115);
}
window.addEventListener("resize", () => { if (state.latest) drawHistogram(state.latest.cells.map(c => c.area_px2)); });

$("#cleanBtn").addEventListener("click", async () => {
  if (!state.image) return;
  $("#cleanBtn").disabled = true; $("#cleanBtn").textContent = "Очистка…";
  try {
    const result = await api("/api/clean", { image: state.image });
    $("#cleanBefore").src = result.original; $("#cleanAfter").src = result.cleaned; $("#cleanNote").textContent = result.note;
    $("#cleanComparison").classList.remove("hidden");
    // Keep the cleaned version ready for an explicit follow-up analysis.
    state.image = result.image; state.synthetic = false; toast("Показано сравнение до и после очистки. Запустите анализ повторно для новых измерений.");
  } catch (error) { toast(error.message); }
  finally { $("#cleanBtn").disabled = false; $("#cleanBtn").textContent = "Сравнить очистку"; }
});

$("#csvBtn").addEventListener("click", async () => {
  if (!state.latest) return;
  try { const blob = await api("/api/export/csv", { analysis_id: state.latest.id }); const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = `cellvision_${state.latest.id}.csv`; a.click(); URL.revokeObjectURL(a.href); }
  catch (error) { toast(error.message); }
});
$("#pdfBtn").addEventListener("click", () => {
  if (!state.latest) return;
  const result = state.latest;
  const popup = window.open("", "_blank");
  if (!popup) return toast("Разрешите всплывающее окно для печати отчёта");
  popup.document.write(`<!doctype html><html lang="ru"><meta charset="utf-8"><title>CellVision report</title><style>body{font:14px Arial;color:#19231f;margin:35px}h1{font-size:22px}img{max-width:47%;max-height:360px;object-fit:contain;border:1px solid #ddd}.pair{display:flex;gap:16px;margin:20px 0}.kv{line-height:1.9}.note{border:1px solid #b7c9c1;background:#f2f8f5;padding:12px;margin:18px 0}@media print{button{display:none}}</style><h1>CellVision · исследовательский отчёт</h1><p>${new Date(result.created_at).toLocaleString("ru-RU")} · ${escapeHtml(result.image_name)}</p><div class="note"><b>${escapeHtml(result.assessment.label)}</b><br>${escapeHtml(result.assessment.detail)}<br><br>Не является диагнозом или медицинским заключением.</div><div class="kv">${Object.entries(result.metrics).map(([k,v])=>`<b>${escapeHtml(k)}:</b> ${escapeHtml(v)}<br>`).join("")}</div><div class="pair"><img src="${result.image_data}"><img src="${result.segmented_data}"></div><p>* CV размерного распределения объектов на изображении; не является лабораторным RDW.</p><button onclick="window.print()">Печать / сохранить в PDF</button><script>window.onload=()=>setTimeout(()=>window.print(),250)<\\/script></html>`);
  popup.document.close();
});
function escapeHtml(value) { return String(value ?? "").replace(/[&<>"']/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[ch])); }

async function loadHistory() {
  if (!state.user) return;
  try {
    const data = await api("/api/history", undefined, "GET"); state.history = data.items;
    const history = data.items;
    $("#historyList").innerHTML = history.length ? history.map(row => `<div class="history-item"><span class="history-number">#${row.id}</span><div><b>${escapeHtml(row.image_name)}</b><small>${new Date(row.created_at).toLocaleString("ru-RU")} · ${row.cells} objects</small></div><button data-history-analysis="${row.id}" class="mini-button">Открыть</button></div>`).join("") : '<div class="empty-state compact"><b>История пока пуста</b><p>Сохранённые анализы появятся здесь.</p></div>';
    const latestId = history[0]?.id;
    $("#compareSelect").innerHTML = history.filter(x => x.id !== latestId).map(row => `<option value="${row.id}">#${row.id} · ${escapeHtml(row.image_name)} · ${new Date(row.created_at).toLocaleDateString("ru-RU")}</option>`).join("") || '<option value="">Нужен более ранний анализ</option>';
    $$('[data-history-analysis]').forEach(button => button.addEventListener("click", async () => {
      const item = history.find(x => x.id === Number(button.dataset.historyAnalysis));
      if (!item) return;
      const assessment = JSON.parse(item.anemia_result || '{"status":"unassessed","label":"Нет оценки","detail":""}');
      state.latest = { ...item, cells: [], metrics: JSON.parse(item.morphology_json || "{}"), assessment };
      $("#resultContent").classList.remove("hidden"); $("#emptyResults").classList.add("hidden");
      $("#assessmentTitle").textContent = assessment.label; $("#assessmentText").textContent = assessment.detail;
      $("#assessmentCard").className = `assessment-card ${assessment.status}`;
      $("#inputResultImage").src = item.image_data; $("#segmentedImage").src = item.segmented_data;
      const m=state.latest.metrics; const stats=[["Сегментировано",item.cells,"объектов"],["Средняя площадь",m.mean_area,"px²"],["Медиана площади",m.median_area,"px²"],["Разброс размеров",m.cv_percent,"% CV*"],["Эквивалентный диаметр",m.mean_diameter,"px"],["Круглость",m.mean_circularity,"0–1"],["Эксцентриситет",m.mean_eccentricity,"0–1"],["1-й квартиль площади",m.q1_area,"px²"],["3-й квартиль площади",m.q3_area,"px²"]];
      $("#metricGrid").innerHTML=stats.map(([n,v,u])=>`<div class="metric-card"><small>${n}</small><b>${v??"—"}</b><span>${u}</span></div>`).join("");
      try { const cellData = await api(`/api/cells?analysis_id=${item.id}`, undefined, "GET"); state.latest.cells = cellData.items; drawHistogram(cellData.items.map(c => c.area_px2)); renderAnnotations(state.latest); renderMaskReview(state.latest); } catch (_) {}
      navigate("analysis");
    }));
  } catch (error) { if (error.message !== "Сначала войдите в систему") toast(error.message); }
}
$("#profileForm").addEventListener("submit", async e => {
  e.preventDefault(); if (!state.user) return showAuth(true);
  const form = new FormData(e.currentTarget); const data = Object.fromEntries(form.entries());
  try { await api("/api/profile", data); state.user = { ...state.user, ...data }; $("#userName").textContent = data.first_name || state.user.username; toast("Профиль сохранён локально"); }
  catch (error) { toast(error.message); }
});

async function loadHospitals() {
  try {
    const { items } = await api("/api/hospitals", undefined, "GET");
    $("#hospitalList").innerHTML = items.map((h, i) => `<article class="hospital-card"><div class="hospital-number">0${i+1}</div><div class="hospital-content"><div class="hospital-title"><div><span class="eyebrow">${escapeHtml(h.type)}</span><h3>${escapeHtml(h.name)}</h3></div><div class="rating"><b>★ ${escapeHtml(h.rating)}</b><small>${escapeHtml(h.rating_source)}</small></div></div><p>${escapeHtml(h.evidence)}</p><div class="hospital-meta"><span>⌖ ${escapeHtml(h.address)}</span><a href="tel:${h.phone.replace(/[^+\d]/g, "")}">☎ ${escapeHtml(h.phone)}</a></div><div class="hospital-actions"><a class="button button-light" href="${h.maps}" target="_blank" rel="noopener">Карта / контакты ↗</a><a class="text-link" href="${h.reviews}" target="_blank" rel="noopener">Отзывы и профиль ↗</a></div></div></article>`).join("");
  } catch (error) { $("#hospitalList").textContent = error.message; }
}
let datasetFile=null;
$("#datasetInput").addEventListener("change",e=>{datasetFile=e.target.files[0]||null;$("#datasetName").textContent=datasetFile?`${datasetFile.name} · ${(datasetFile.size/1048576).toFixed(1)} МБ`:"Файл не выбран";$("#trainModel").disabled=!datasetFile;});
$("#trainModel").addEventListener("click",()=>{
  if(!datasetFile)return;if(datasetFile.size>64*1048576)return toast("ZIP должен быть не больше 64 МБ");
  const reader=new FileReader();reader.onload=async()=>{const btn=$("#trainModel");btn.disabled=true;btn.textContent="Обучение…";
    try{const r=await api("/api/model/train",{archive:reader.result.split(",")[1]});$("#modelBadge").textContent=`ЭКСПЕРИМЕНТАЛЬНАЯ · ${r.classes.length} КЛАССОВ`;
      state.aiClasses=r.classes; $("#modelReport").innerHTML=`<div class="model-report"><b>Train ${r.train_n} · Test ${r.test_n} · Accuracy ${(r.accuracy*100).toFixed(1)}% · macro-F1 ${r.macro_f1}</b><div class="class-metrics">${Object.entries(r.per_class).map(([k,v])=>`<span><b>${escapeHtml(k)}</b> · n=${v.n} · P ${v.precision} · R ${v.recall} · F1 ${v.f1}</span>`).join("")}</div><details><summary>Матрица ошибок</summary><pre>${escapeHtml(JSON.stringify(r.confusion_matrix,null,2))}</pre></details><p>${escapeHtml(r.warning)}</p></div>`;toast("Обучено; это внутренняя оценка набора данных.");
    }catch(err){toast(err.message);}finally{btn.disabled=!datasetFile;btn.textContent="Обучить и оценить";}};reader.readAsDataURL(datasetFile);
});
async function loadModelStatus(){try{const r=await api("/api/model/status",undefined,"GET");state.aiClasses=r.classes||[];$("#modelBadge").textContent=r.trained?`ЭКСПЕРИМЕНТАЛЬНАЯ · ${r.classes.length} КЛАССОВ`:"МОДЕЛЬ НЕ ОБУЧЕНА";}catch(_){}}
$("#compareBtn").addEventListener("click", async () => {
  if (!state.user) return showAuth(true);
  if (!state.latest) { toast("Сначала выполните новый анализ"); return; }
  const id = $("#compareSelect").value; if (!id) return toast("Выберите прошлый анализ в истории");
  try { const result = await api("/api/compare", { analysis_id: Number(id) }); renderComparison(result.before, result.after); }
  catch (error) { toast(error.message); }
});
function renderComparison(before, after) {
  const oldM=JSON.parse(before.morphology_json||"{}"), newM=JSON.parse(after.morphology_json||"{}"), fmt=x=>Number(x||0).toLocaleString("ru-RU",{maximumFractionDigits:2});
  const metrics=[["Количество объектов",before.cells,after.cells,""],["Средняя площадь",oldM.mean_area,newM.mean_area,"px²"],["Медиана площади",oldM.median_area,newM.median_area,"px²"],["CV разброса размеров",oldM.cv_percent,newM.cv_percent,"%"],["Средняя круглость",oldM.mean_circularity,newM.mean_circularity,""]];
  $("#compareEmpty").classList.add("hidden"); $("#compareResult").classList.remove("hidden");
  $("#compareResult").innerHTML=`<div class="compare-images"><article><div class="compare-label"><span>ДО</span><b>${escapeHtml(before.image_name)}</b><small>${new Date(before.created_at).toLocaleString("ru-RU")}</small></div><img src="${before.image_data}" alt="До"><img class="mini-segment" src="${before.segmented_data}" alt="Сегментация до"></article><div class="compare-arrow">→</div><article><div class="compare-label"><span>ПОСЛЕ</span><b>${escapeHtml(after.image_name)}</b><small>${new Date(after.created_at).toLocaleString("ru-RU")}</small></div><img src="${after.image_data}" alt="После"><img class="mini-segment" src="${after.segmented_data}" alt="Сегментация после"></article></div><div class="compare-table"><div class="compare-row compare-heading"><span>Показатель</span><span>До</span><span>После</span><span>Изменение</span></div>${metrics.map(([label,a,b,unit])=>`<div class="compare-row"><span>${label}</span><b>${fmt(a)} ${unit}</b><b>${fmt(b)} ${unit}</b><span>${a&&b?`${(Number(b)-Number(a)>0?"+":"")}${fmt(Number(b)-Number(a))} ${unit}`:"—"}</span></div>`).join("")}</div><div class="compare-disclaimer">Показаны разные изображения и измерения в пикселях. Изменение результата зависит от съёмки, окраски, фокусировки и сегментации. Это не показатель эффективности лечения.</div>`;
}

$("#explainBtn").addEventListener("click", () => { $("#explainStrip").scrollIntoView({behavior:"smooth",block:"center"}); $("#explainStrip").classList.add("highlight"); setTimeout(()=>$("#explainStrip").classList.remove("highlight"),1600); });
async function boot() {
  try { const data = await api("/api/me", undefined, "GET"); setUser(data.user); } catch (_) { showAuth(true); }
  if (state.user) {
    const form = $("#profileForm");
    for (const key of ["first_name", "last_name", "age", "home_address"]) if (state.user[key] != null) form.elements[key].value = state.user[key];
  }
  await loadHospitals();
  loadModelStatus();
  const name = location.hash.slice(1); if (name && $("#view-" + name)) navigate(name);
}
boot();
