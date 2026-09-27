(() => {
  const fields=[{key:"hb",name:"Гемоглобин"},{key:"mcv",name:"MCV"},{key:"mch",name:"MCH"},{key:"rdw",name:"RDW"},{key:"ferritin",name:"Ферритин"},{key:"iron",name:"Сывороточное железо"},{key:"tsat",name:"Насыщение трансферрина"},{key:"b12",name:"Витамин B₁₂"},{key:"folate",name:"Фолат"}];
  const $=id=>document.getElementById(id);
  $("causeForm").addEventListener("submit",event=>{
    event.preventDefault();const rows=[];
    for(const f of fields){const value=Number($(f.key).value),low=Number($(f.key+"Low").value),high=Number($(f.key+"High").value),unit=$(f.key+"Unit").value.trim();
      if($(f.key).value==="")continue;
      if($(f.key+"Low").value===""||$(f.key+"High").value===""||!Number.isFinite(value)||!Number.isFinite(low)||!Number.isFinite(high)||low>=high){rows.push({name:f.name,state:"Недостаточно данных для сравнения",unit});continue;}
      rows.push({name:f.name,value,unit,state:value<low?"Ниже интервала лаборатории":value>high?"Выше интервала лаборатории":"В пределах интервала лаборатории",flag:value<low?"low":value>high?"high":"normal"});
    }
    if(!rows.length){$("causeResult").innerHTML="<h2>Нужны значения</h2><p>Введите хотя бы один показатель и референсные границы с бланка.</p>";return;}
    const low=new Set(rows.filter(r=>r.flag==="low").map(r=>r.name)),high=new Set(rows.filter(r=>r.flag==="high").map(r=>r.name)),ironPattern=low.has("Ферритин")&&low.has("Насыщение трансферрина"),b12Pattern=low.has("Витамин B₁₂"),folatePattern=low.has("Фолат");
    const patterns=[];if(low.has("Гемоглобин"))patterns.push("Гемоглобин ниже референсного интервала этого бланка; это требует лабораторной оценки анемии специалистом, но здесь не является диагнозом.");if(ironPattern&&low.has("MCV"))patterns.push("Низкие MCV, ферритин и насыщение трансферрина могут образовывать микроцитарный паттерн, требующий оценки обмена железа; они не устанавливают причину.");else if(ironPattern)patterns.push("Сочетание низких ферритина и насыщения трансферрина может требовать оценки обмена железа; это не устанавливает причину.");if((b12Pattern||folatePattern)&&high.has("MCV"))patterns.push("Повышенный MCV вместе с низким B₁₂ или фолатом может соответствовать макроцитарному паттерну; нужны клиническая оценка и дополнительные данные.");else if(b12Pattern||folatePattern)patterns.push("Есть значение ниже интервала среди B₁₂/фолата. Его интерпретируют вместе с CBC и клинической картиной.");
    if(!patterns.length)patterns.push("По введённым результатам характерное сочетание не выявлено либо введённых данных недостаточно. Это не исключает дефицит или заболевание.");
    const html=rows.map(r=>`<tr><th>${r.name}</th><td>${r.value??"—"} ${escapeHtml(r.unit||"")}</td><td class="${r.flag||""}">${r.state}</td></tr>`).join("");
    $("causeResult").innerHTML=`<h2>Сопоставление с указанными интервалами</h2><div class="cause-table-wrap"><table class="cause-output"><thead><tr><th>Показатель</th><th>Результат</th><th>Сравнение</th></tr></thead><tbody>${html}</tbody></table></div><h3>Возможные лабораторные паттерны</h3><ul>${patterns.map(x=>`<li>${x}</li>`).join("")}</ul><p><b>Обсудите полный бланк с медицинским специалистом.</b> Это сравнение референсных границ, не диагноз, не вероятность анемии и не назначение лечения.</p>`;
  });
  function escapeHtml(value){return String(value).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));}
})();
