(() => {
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const wavelength = $("#wavelength"), brightness = $("#lampBrightness"), spectrum = $("#spectrumCanvas");
  if (!wavelength || !spectrum) return;

  const samples = {
    oxy: { name: "оксигемоглобина", color: "#ef5665", curve: nm => .12 + .55*Math.exp(-(((nm-542)/17)**2)) + .42*Math.exp(-(((nm-577)/20)**2)) },
    deoxy: { name: "дезоксигемоглобина", color: "#9555ca", curve: nm => .1 + .69*Math.exp(-(((nm-555)/32)**2)) },
    dye: { name: "безопасного красителя", color: "#f19049", curve: nm => .08 + .72*Math.exp(-(((nm-520)/29)**2)) }
  };
  const allowedProgress = new Set(["green", "gradient", "cpi", "board"]);
  const artifactDone = new Set();
  let savedProgress = [];
  try { savedProgress = JSON.parse(localStorage.getItem("cv_lab_done") || "[]"); } catch (_) {}
  const state = { sample: "oxy", lit: false, sourceName: "синтетический учебный пример", completed: new Set(savedProgress.filter(key => allowedProgress.has(key))) };
  const smear = document.createElement("canvas"); smear.width = 480; smear.height = 270;
  const smearCtx = smear.getContext("2d", { willReadFrequently: true });
  const rgbView = $("#gradientSource"), edgeView = $("#gradientResult"), threshold = $("#gradientThreshold");

  function wavelengthColor(nm) {
    if (nm < 490) return "#5985ff";
    if (nm < 520) return "#4acdb5";
    if (nm < 565) return "#91d943";
    if (nm < 590) return "#d8d841";
    if (nm < 625) return "#ff9b42";
    return "#f05c68";
  }
  function absorbance(nm) { return Math.min(.94, Math.max(.025, samples[state.sample].curve(nm))); }
  function complete(key) {
    state.completed.add(key);
    localStorage.setItem("cv_lab_done", JSON.stringify([...state.completed]));
    $("#labPoints").textContent = state.completed.size;
    const ids = { green: "greenLab", gradient: "gradientLab", cpi: "paleLab", board: "boardLab" };
    $("#" + ids[key])?.classList.add("experiment-done");
  }
  function drawSpectrum() {
    const canvas = spectrum, ctx = canvas.getContext("2d"), rect = canvas.getBoundingClientRect();
    if (!rect.width) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(rect.width*dpr); canvas.height = Math.round(180*dpr); ctx.setTransform(dpr,0,0,dpr,0,0);
    const w=rect.width,h=180,left=37,right=12,top=13,bottom=28;
    ctx.clearRect(0,0,w,h);ctx.font="10px Manrope, sans-serif";ctx.strokeStyle="#e8eee9";ctx.fillStyle="#96a29a";ctx.lineWidth=1;
    for(let tick=0;tick<=100;tick+=50){const y=top+(h-top-bottom)*(1-tick/100);ctx.beginPath();ctx.moveTo(left,y);ctx.lineTo(w-right,y);ctx.stroke();ctx.fillText(`${tick}%`,3,y+3);}
    const xFor=nm=>left+(nm-430)/220*(w-left-right),yFor=value=>top+(h-top-bottom)*(1-value);
    const grad=ctx.createLinearGradient(left,0,w-right,0);[[0,"#718cff"],[.28,"#52d4c0"],[.5,"#a7da53"],[.68,"#ffd353"],[1,"#ef6577"]].forEach(([at,color])=>grad.addColorStop(at,color));
    ctx.globalAlpha=.22;ctx.fillStyle=grad;ctx.fillRect(left,h-bottom+3,w-left-right,4);ctx.globalAlpha=1;
    ctx.beginPath();for(let nm=430;nm<=650;nm+=2){const x=xFor(nm),y=yFor(absorbance(nm));if(nm===430)ctx.moveTo(x,y);else ctx.lineTo(x,y);}ctx.lineTo(xFor(650),h-bottom);ctx.lineTo(xFor(430),h-bottom);ctx.closePath();ctx.globalAlpha=.13;ctx.fillStyle=samples[state.sample].color;ctx.fill();ctx.globalAlpha=1;
    ctx.beginPath();for(let nm=430;nm<=650;nm+=2){const x=xFor(nm),y=yFor(absorbance(nm));if(nm===430)ctx.moveTo(x,y);else ctx.lineTo(x,y);}ctx.strokeStyle=samples[state.sample].color;ctx.lineWidth=2.5;ctx.stroke();
    const markX=xFor(Number(wavelength.value));ctx.setLineDash([3,4]);ctx.strokeStyle="#3b5346";ctx.beginPath();ctx.moveTo(markX,top);ctx.lineTo(markX,h-bottom);ctx.stroke();ctx.setLineDash([]);
    ctx.fillStyle="#7d8981";ctx.font="9px Manrope, sans-serif";[[430,"430"],[490,"490"],[550,"550"],[610,"610"],[650,"650"]].forEach(([nm,label])=>ctx.fillText(label,xFor(nm)-8,h-8));
  }
  function updateLamp() {
    const nm=Number(wavelength.value),color=wavelengthColor(nm),absorb=absorbance(nm),light=Number(brightness.value),transmission=Math.round((1-absorb)*100);
    $("#wavelengthValue").textContent=nm;$("#lampBrightnessValue").textContent=light;$("#absorptionValue").textContent=`${Math.round(absorb*100)}%`;
    $("#lampBulb").style.setProperty("--lamp-color",color);$("#lampScene").style.setProperty("--lamp-color",color);$("#lampScene").style.setProperty("--light-intensity",String(light/100));$("#lampScene").style.setProperty("--absorb",String(absorb));$("#cuvetteLiquid").style.setProperty("--sample-color",samples[state.sample].color);
    $("#transmissionNumber").textContent=state.lit?`${transmission}%`:"—%";
    $("#lampExplanation").textContent=state.lit?`В этой условной модели образец ${samples[state.sample].name} поглощает около ${Math.round(absorb*100)}% света при ${nm} nm; относительное прохождение — около ${transmission}%. Это учебное число модели, а не лабораторное измерение.`:"Нажми «Включить лампу», чтобы увидеть результат модели.";
    $("#lampScene").classList.toggle("lamp-on",state.lit);drawSpectrum();
  }
  function seedSmear(seed=28) {
    let value=seed>>>0;const random=()=>{value=(value*1664525+1013904223)>>>0;return value/4294967296;};
    const w=smear.width,h=smear.height;smearCtx.fillStyle="#f3f0e9";smearCtx.fillRect(0,0,w,h);
    const colors=[["#ce7780","#f0c6bd"],["#c66b78","#ebbbb7"],["#d27d83","#f3d1c5"]];
    for(let i=0;i<74;i++){
      const x=10+random()*(w-20),y=10+random()*(h-20),r=7+random()*9,ell=.72+random()*.5,[edge,center]=colors[Math.floor(random()*colors.length)];
      smearCtx.save();smearCtx.translate(x,y);smearCtx.rotate(random()*Math.PI);smearCtx.scale(ell,1);
      const g=smearCtx.createRadialGradient(-r*.17,-r*.18,r*.13,0,0,r);g.addColorStop(0,center);g.addColorStop(.35,center);g.addColorStop(.58,edge);g.addColorStop(.76,"#e4a4a1");g.addColorStop(1,"#f3d4cc");
      smearCtx.fillStyle=g;smearCtx.beginPath();smearCtx.arc(0,0,r,0,Math.PI*2);smearCtx.fill();smearCtx.strokeStyle="#b86470";smearCtx.globalAlpha=.48;smearCtx.lineWidth=1.1;smearCtx.stroke();smearCtx.restore();
    }
    for(let i=0;i<4;i++){const x=20+random()*(w-40),y=15+random()*(h-30);smearCtx.fillStyle="#6651a6";smearCtx.beginPath();smearCtx.arc(x,y,7+random()*3,0,Math.PI*2);smearCtx.fill();}
    state.sourceName="синтетический учебный пример";
  }
  function edgeImage(imageData,cutoff) {
    const {width:w,height:h,data}=imageData,out=new ImageData(w,h),gray=new Float32Array(w*h);let count=0;
    for(let i=0,p=0;i<data.length;i+=4,p++)gray[p]=.299*data[i]+.587*data[i+1]+.114*data[i+2];
    for(let y=1;y<h-1;y++)for(let x=1;x<w-1;x++){
      const p=y*w+x;
      const gx=-gray[p-w-1]+gray[p-w+1]-2*gray[p-1]+2*gray[p+1]-gray[p+w-1]+gray[p+w+1];
      const gy=-gray[p-w-1]-2*gray[p-w]-gray[p-w+1]+gray[p+w-1]+2*gray[p+w]+gray[p+w+1];
      const strength=Math.hypot(gx,gy)/4,idx=p*4;
      if(strength>=cutoff){const glow=Math.min(255,110+strength);out.data[idx]=238;out.data[idx+1]=Math.min(255,180+strength*.35);out.data[idx+2]=78;out.data[idx+3]=glow;count++;}
      else {out.data[idx]=20;out.data[idx+1]=24;out.data[idx+2]=43;out.data[idx+3]=255;}
    }
    for(let x=0;x<w;x++)for(const y of [0,h-1]){const i=(y*w+x)*4;out.data.set([20,24,43,255],i);}
    for(let y=0;y<h;y++)for(const x of [0,w-1]){const i=(y*w+x)*4;out.data.set([20,24,43,255],i);}
    return {image:out,count};
  }
  function greenImage(imageData) {
    const out=new ImageData(imageData.width,imageData.height),a=imageData.data,b=out.data;
    for(let i=0;i<a.length;i+=4){const green=a[i+1];b[i]=Math.round(green*.12);b[i+1]=green;b[i+2]=Math.round(green*.18);b[i+3]=255;}
    return out;
  }
  function drawProfile(canvas,imageData,row=Math.floor(imageData.height/2),lineColor="#37d4a5") {
    const ctx=canvas.getContext("2d"),w=canvas.width,h=canvas.height,data=imageData.data,iw=imageData.width,ih=imageData.height;
    ctx.clearRect(0,0,w,h);ctx.fillStyle="#171e34";ctx.fillRect(0,0,w,h);
    const x0=32,y0=13,pw=w-44,ph=h-39;
    ctx.strokeStyle="#394057";ctx.lineWidth=1;for(let i=0;i<=4;i++){const y=y0+ph*i/4;ctx.beginPath();ctx.moveTo(x0,y);ctx.lineTo(x0+pw,y);ctx.stroke();}
    ctx.fillStyle="#aeb7c4";ctx.font="11px Arial";ctx.fillText("Яркость",5,11);ctx.fillText("x · пиксели",x0+pw-70,h-8);
    ctx.beginPath();for(let x=0;x<iw;x++){const i=(row*iw+x)*4,g=.299*data[i]+.587*data[i+1]+.114*data[i+2],px=x0+x/(iw-1)*pw,py=y0+(1-g/255)*ph;if(x===0)ctx.moveTo(px,py);else ctx.lineTo(px,py);}ctx.strokeStyle=lineColor;ctx.lineWidth=2.5;ctx.stroke();
    const scanY=y0+ph*(1-row/(ih-1));ctx.setLineDash([5,4]);ctx.strokeStyle="#dce4ef88";ctx.beginPath();ctx.moveTo(x0,scanY);ctx.lineTo(x0+pw,scanY);ctx.stroke();ctx.setLineDash([]);
  }
  function drawBoard() {
    const source=smearCtx.getImageData(0,0,smear.width,smear.height),edge=edgeImage(source,Number(threshold.value)||58),green=greenImage(source);
    $("#gradientSource").getContext("2d").putImageData(source,0,0);$("#gradientResult").getContext("2d").putImageData(edge.image,0,0);
    $("#gradientThresholdValue").textContent=threshold.value;$("#gradientStats").textContent=`Пиксели границ выше порога: ${edge.count.toLocaleString("ru-RU")}`;
    [["panelRgb",source],["panelGreen",green],["panelEdge",edge.image]].forEach(([id,image])=>$("#"+id).getContext("2d").putImageData(image,0,0));
    drawProfile($("#panelProfile"),green,Math.floor(green.height/2));$("#boardSourceName").textContent=state.sourceName;
  }
  function drawCpi() {
    const canvas=$("#paleCell"),ctx=canvas.getContext("2d",{willReadFrequently:true}),center=Number($("#paleCenter").value),cx=130,cy=105,rx=98,ry=68;
    ctx.clearRect(0,0,canvas.width,canvas.height);ctx.fillStyle="#fbf7f1";ctx.fillRect(0,0,canvas.width,canvas.height);
    const body=ctx.createRadialGradient(cx,cy,10,cx,cy,rx);body.addColorStop(0,"#e4a7a2");body.addColorStop(.56,"#d48988");body.addColorStop(.79,"#bc6872");body.addColorStop(1,"#aa5862");
    ctx.save();ctx.translate(cx,cy);ctx.scale(1,ry/rx);ctx.fillStyle=body;ctx.beginPath();ctx.arc(0,0,rx,0,Math.PI*2);ctx.fill();ctx.restore();
    const gray=Math.round(65+center*1.35),pale=`rgb(${gray},${gray-7},${gray-8})`;
    const inner=ctx.createRadialGradient(cx-7,cy-9,3,cx,cy,rx*.59);inner.addColorStop(0,pale);inner.addColorStop(.64,pale);inner.addColorStop(1,"#d08a8b");
    ctx.save();ctx.translate(cx,cy);ctx.scale(1,ry/rx);ctx.fillStyle=inner;ctx.beginPath();ctx.arc(0,0,rx*.61,0,Math.PI*2);ctx.fill();ctx.restore();
    ctx.strokeStyle="#385b48";ctx.setLineDash([5,4]);ctx.lineWidth=1.5;ctx.beginPath();ctx.moveTo(14,cy);ctx.lineTo(246,cy);ctx.stroke();ctx.setLineDash([]);
    ctx.fillStyle="#475d50";ctx.font="10px Arial";ctx.fillText("A",8,cy-7);ctx.fillText("A",245,cy-7);
    const pixels=ctx.getImageData(0,0,canvas.width,canvas.height),lum=(x,y)=>{const i=(y*canvas.width+x)*4,d=pixels.data;return .299*d[i]+.587*d[i+1]+.114*d[i+2];};
    const centerValues=[],rimValues=[];for(let y=cy-7;y<=cy+7;y++)for(let x=cx-16;x<=cx+16;x++)centerValues.push(lum(x,y));
    for(let y=cy-7;y<=cy+7;y++)for(let x of [cx-84,cx-78,cx+78,cx+84])rimValues.push(lum(x,y));
    const avg=values=>values.reduce((a,b)=>a+b,0)/values.length,cpi=avg(centerValues)/avg(rimValues);
    $("#paleCenterValue").textContent=center;$("#cpiValue").textContent=cpi.toFixed(2);
    const profile=$("#paleProfile"),pctx=profile.getContext("2d");pctx.clearRect(0,0,profile.width,profile.height);pctx.fillStyle="#171e34";pctx.fillRect(0,0,profile.width,profile.height);
    const left=36,top=17,pw=profile.width-52,ph=profile.height-46;
    pctx.strokeStyle="#394057";for(let i=0;i<=4;i++){const y=top+ph*i/4;pctx.beginPath();pctx.moveTo(left,y);pctx.lineTo(left+pw,y);pctx.stroke();}
    pctx.fillStyle="#b5becc";pctx.font="11px Arial";pctx.fillText("Яркость",5,12);pctx.fillText("сечение клетки →",left+pw-100,profile.height-8);
    pctx.beginPath();for(let x=15;x<245;x++){const y=cy,px=left+(x-15)/229*(profile.width-left-16),py=top+(1-lum(x,y)/255)*ph;if(x===15)pctx.moveTo(px,py);else pctx.lineTo(px,py);}pctx.strokeStyle="#42d5ab";pctx.lineWidth=2.5;pctx.stroke();
    const desc=center<58?"В этой схеме центр темнее относительно выбранного ободка.":center<72?"В этой схеме центральная зона имеет промежуточную яркость.":"В этой схеме центр светлее относительно выбранного ободка. Это свойство рисунка, не диагноз.";
    $("#paleInterpretation").textContent=`${desc} Измерение выполнено на синтетической схеме.`;
  }
  function seedSmear(seed=(Date.now()>>>0)) {
    let value=seed>>>0;const random=()=>{value=(value*1664525+1013904223)>>>0;return value/4294967296;};
    const w=smear.width,h=smear.height;smearCtx.fillStyle="#f3f0e9";smearCtx.fillRect(0,0,w,h);
    const colors=[["#ce7780","#f0c6bd"],["#c66b78","#ebbbb7"],["#d27d83","#f3d1c5"]];
    for(let i=0;i<74;i++){const x=10+random()*(w-20),y=10+random()*(h-20),r=7+random()*9,ell=.72+random()*.5,[edge,center]=colors[Math.floor(random()*colors.length)];smearCtx.save();smearCtx.translate(x,y);smearCtx.rotate(random()*Math.PI);smearCtx.scale(ell,1);const g=smearCtx.createRadialGradient(-r*.17,-r*.18,r*.13,0,0,r);g.addColorStop(0,center);g.addColorStop(.35,center);g.addColorStop(.58,edge);g.addColorStop(.76,"#e4a4a1");g.addColorStop(1,"#f3d4cc");smearCtx.fillStyle=g;smearCtx.beginPath();smearCtx.arc(0,0,r,0,Math.PI*2);smearCtx.fill();smearCtx.strokeStyle="#b86470";smearCtx.globalAlpha=.48;smearCtx.lineWidth=1.1;smearCtx.stroke();smearCtx.restore();}
    for(let i=0;i<4;i++){const x=20+random()*(w-40),y=15+random()*(h-30);smearCtx.fillStyle="#6651a6";smearCtx.beginPath();smearCtx.arc(x,y,7+random()*3,0,Math.PI*2);smearCtx.fill();}
    state.sourceName="синтетический учебный пример";drawBoard();
  }

  wavelength.addEventListener("input",updateLamp);brightness.addEventListener("input",updateLamp);
  $("#labSample").addEventListener("change",event=>{state.sample=event.target.value;updateLamp();});
  $("#lampRun").addEventListener("click",event=>{state.lit=!state.lit;event.currentTarget.innerHTML=state.lit?"Выключить лампу <span>◌</span>":"Включить лампу <span>↗</span>";updateLamp();if(state.lit)complete("green");});
  $$('[data-scroll-lab]').forEach(button=>button.addEventListener("click",()=>$("#"+button.dataset.scrollLab).scrollIntoView({behavior:"smooth",block:"start"})));
  $$("[data-quiz]").forEach(button=>button.addEventListener("click",()=>{const correct=button.dataset.quiz==="right";$("#quizFeedback").textContent=correct?"Верно! Модель иллюстрирует только взаимодействие света и образца.":"Пока нет: эта виртуальная установка не измеряет Hb и не определяет заболевание.";$("#quizFeedback").classList.toggle("correct",correct);if(correct)complete("green");}));
  $("#gradientThreshold").addEventListener("input",()=>{drawBoard();complete("gradient");});
  $("#regenerateSmear").addEventListener("click",()=>{seedSmear();complete("gradient");});
  $("#refreshBoard").addEventListener("click",()=>{drawBoard();complete("board");});
  $("#paleCenter").addEventListener("input",()=>{drawCpi();complete("cpi");});
  $$('[data-pale]').forEach(button=>button.addEventListener("click",()=>{$("#paleCenter").value=button.dataset.pale;drawCpi();complete("cpi");}));
  $$('[data-artifact]').forEach(button=>button.addEventListener("click",()=>{const card=button.closest(".artifact-case"),correct=button.dataset.correct==="1";const feedback=card.querySelector("small");feedback.textContent=correct?"Верно. Сначала проверьте качество кадра; сомнительные детали сохраняйте для ручной проверки.":"Не лучший следующий шаг. Попробуйте другой вариант.";feedback.classList.toggle("right",correct);if(correct){card.querySelectorAll("button").forEach(b=>b.disabled=true);artifactDone.add(button.dataset.artifact);$("#artifactScore").textContent=`Выполнено: ${artifactDone.size} из 4`;if(artifactDone.size===4)complete("board");}}));
  $("#smearUpload").addEventListener("change",event=>{const file=event.target.files?.[0];if(!file)return;const url=URL.createObjectURL(file),image=new Image();image.onload=()=>{smearCtx.fillStyle="#f3f0e9";smearCtx.fillRect(0,0,smear.width,smear.height);const scale=Math.min(smear.width/image.width,smear.height/image.height),w=image.width*scale,h=image.height*scale;smearCtx.drawImage(image,(smear.width-w)/2,(smear.height-h)/2,w,h);state.sourceName=file.name;drawBoard();complete("gradient");URL.revokeObjectURL(url);};image.onerror=()=>{URL.revokeObjectURL(url);alert("Не удалось открыть это изображение.");};image.src=url;});
  $("#downloadBoard").addEventListener("click",()=>{
    const width=1200,height=860,gap=28,outer=38,panelW=(width-outer*2-gap)/2,panelH=335,board=document.createElement("canvas");board.width=width;board.height=height;const ctx=board.getContext("2d");
    ctx.fillStyle="#151b30";ctx.fillRect(0,0,width,height);ctx.fillStyle="#eef2f6";ctx.font="700 24px Arial";ctx.fillText("CELLVISION · ВИЗУАЛЬНАЯ ЛАБОРАТОРИЯ",outer,43);ctx.fillStyle="#aeb8c4";ctx.font="14px Arial";ctx.fillText(state.sourceName+" · учебная визуализация, не диагноз",outer,68);
    const panels=[["A · RGB / исходное изображение","panelRgb"],["B · зелёный RGB-канал / имитация","panelGreen"],["C · градиентная карта Sobel","panelEdge"],["D · профиль яркости по сечению","panelProfile"]];
    panels.forEach(([title,id],i)=>{const x=outer+(i%2)*(panelW+gap),y=94+Math.floor(i/2)*(panelH+gap),source=$("#"+id);ctx.fillStyle="#202740";ctx.beginPath();ctx.roundRect(x,y,panelW,panelH,10);ctx.fill();ctx.fillStyle="#edf2f3";ctx.font="700 15px Arial";ctx.fillText(title,x+14,y+24);ctx.drawImage(source,x+12,y+38,panelW-24,panelH-52);});
    const link=document.createElement("a");link.download="cellvision-lab-board.png";link.href=board.toDataURL("image/png");link.click();complete("board");
  });
  window.addEventListener("resize",drawSpectrum);
  for(const key of state.completed){const ids={green:"greenLab",gradient:"gradientLab",cpi:"paleLab",board:"boardLab"};$("#"+ids[key])?.classList.add("experiment-done");}
  $("#labPoints").textContent=state.completed.size;
  seedSmear(28);drawCpi();updateLamp();
})();
