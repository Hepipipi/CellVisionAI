from pathlib import Path
import re

root = Path(r"C:\Users\User\OneDrive\Рабочий стол\CellVision_AI")
index = root / "web" / "index.html"
html = index.read_text(encoding="utf-8")
new_research = '''<section id="view-research" class="view">
        <div class="intro-row"><div><h2>Исследовательский режим</h2><p>Инструменты для просмотра микрофотографий и учебной работы. Автоматические результаты пока требуют независимой проверки.</p></div><span class="tag" id="modelBadge">МОДЕЛЬ НЕ ОБУЧЕНА</span></div>
        <div class="panel research-panel">
          <h3>Морфология клеток</h3><p>Прототип показывает сегментированные объекты, измерения и исследовательскую классификацию отдельных клеток. Классификация форм не устанавливает анемию и не заменяет оценку специалиста.</p>
          <h3>Лабораторный бланк</h3><p>Можно внести значения CBC или загрузить бланк для OCR. После проверки распознанных полей сайт сравнивает гемоглобин с выбранным порогом и описывает эритроцитарные индексы. Процент экспериментальной CBC-модели не показывается: её качество не подтверждено независимой клинической проверкой.</p>
          <h3>Обучение классификатора</h3><p>Для локального эксперимента выберите ZIP с изображениями клеток в отдельных папках train и test. Результат будет относиться только к предоставленной выборке.</p>
          <label class="button button-light file-label">Выбрать ZIP датасет<input id="datasetInput" type="file" accept=".zip" hidden></label> <span id="datasetName">Файл не выбран</span> <button id="trainModel" class="button button-primary" disabled>Обучить и оценить</button><div id="modelReport"></div>
          <p class="hb-help">Чтобы оценить переносимость, разделяйте снимки по пациентам и мазкам до извлечения клеток. Нужны независимые изображения и согласованная экспертная разметка.</p>
        </div>
        <div class="panel protocol-panel"><h3>Следующий этап проверки</h3><ol><li>Зафиксировать источник данных, тип окраски, микроскоп и число исходных снимков.</li><li>Разделить снимки по пациентам и мазкам на разработку и независимый тест.</li><li>Попросить двух наблюдателей независимо отметить контуры и морфологию клеток.</li><li>Сопоставить автоматическую сегментацию с эталонными масками и разобрать ошибки.</li><li>Проверить модель на снимках другого источника или микроскопа.</li></ol><p><b>Открытые материалы для будущей работы:</b> <a href="https://doi.org/10.5281/zenodo.7801430" target="_blank" rel="noopener">RedTell DSE</a> · <a href="https://data.mendeley.com/datasets/hms3sjzt7f/1" target="_blank" rel="noopener">AneRBC</a> · <a href="https://doi.org/10.6084/m9.figshare.13053968" target="_blank" rel="noopener">Expert Annotated RBC</a> · <a href="https://github.com/Shenggan/BCCD_Dataset" target="_blank" rel="noopener">BCCD</a>. Данные требуют проверки лицензии и пригодности перед использованием.</p></div>
      </section>'''
html, count = re.subn(r'<section id="view-research" class="view">.*?</section>', new_research, html, count=1, flags=re.S)
if count != 1:
    raise SystemExit("Could not replace research section")
index.write_text(html, encoding="utf-8")

js_path = root / "web" / "app.js"
js = js_path.read_text(encoding="utf-8")
old = '''    const risk=result.cbc_probability||{};
    if(risk.probability!=null) {
      const model=document.createElement("p");
      model.textContent=`Экспериментальная модель малого набора: ${risk.probability}% — ${risk.detail} Это не клиническая вероятность анемии.`;
      box.append(model);
    }
'''
if old in js:
    js = js.replace(old, "")
js = js.replace('  const photo=result.image_screen||{};$("#imageScreenText").textContent=photo.probability==null?photo.detail:`${photo.label}: ${photo.probability}% · ${photo.detail}`;\n  const risk=result.cbc_probability||assessment.cbc_probability||{};$("#cbcProbabilityText").classList.toggle("hidden",risk.probability==null);$("#cbcProbabilityText").textContent=risk.probability==null?"":`Экспериментальная оценка набора Kaggle: ${risk.probability}% · ${risk.detail}`;\n', '  const photo=result.image_screen||{};$("#imageScreenText").textContent=photo.detail||"Фото мазка используется для визуализации морфологии; вероятность анемии по снимку не выводится.";\n')
js_path.write_text(js, encoding="utf-8")

html = index.read_text(encoding="utf-8")
html = html.replace('<div class="hb-help">Если показатель неизвестен, оставьте поле пустым. CBC-модель оценивает совпадение с меткой anemia небольшого набора Kaggle по MCV, MCH, MCHC и группе пола (Hb не подаётся модели). Результат на тестовой части ограниченный и не является диагнозом. Возраст профиля используется только для ограничения взрослой группы.', '<div class="hb-help">Если показатель неизвестен, оставьте поле пустым. Hb сравнивается с выбранным порогом, а индексы описываются как ориентировочный паттерн. Экспериментальная CBC-модель не выводится как вероятность анемии. Возраст профиля используется только для ограничения взрослой группы.')
html = html.replace('<div class="whole-image-card"><b>Оценка по лабораторным показателям</b><p id="cbcProbabilityText"></p><p id="imageScreenText"></p>', '<div class="whole-image-card"><b>Лабораторные показатели и изображение</b><p id="imageScreenText"></p>')
html, count = re.subn(r'        <div class="panel validation-result">.*?(?=      </section>)', '', html, count=1, flags=re.S)
if count != 1 and 'validation-result' in html:
    raise SystemExit("Could not remove public validation metrics panel")
index.write_text(html, encoding="utf-8")

evidence = root / "web" / "evidence.html"
evidence_html = '''<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Возможности и статус исследования · CellVision</title><link rel="stylesheet" href="/styles.css"><link rel="stylesheet" href="/evidence.css"></head>
<body><main class="evidence-page"><a href="/#research">← CellVision · исследование</a>
<header><span class="tag">ВОЗМОЖНОСТИ ПРОТОТИПА</span><h1>Инструменты для изучения микрофотографий</h1><p>CellVision объединяет обработку изображения, измерения сегментированных объектов и учебные материалы в локальном веб-прототипе.</p></header>
<section><h2>Что можно показать в программе</h2><ul>
<li><b>Контроль кадра:</b> ориентиры резкости, яркости, пересвета и неоднородности освещения, а также подсказки перед пересъёмкой.</li>
<li><b>Обработка изображения:</b> визуальное сравнение очистки шума, исходного кадра и результата сегментации.</li>
<li><b>Измерения объектов:</b> площадь, эквивалентный диаметр, круглость и эксцентриситет; при введённой калибровке — размеры в микрометрах.</li>
<li><b>Рабочие материалы:</b> таблица по объектам в CSV, печатный PDF-отчёт, история анализов, атлас и учебная лаборатория.</li>
<li><b>Ручная проверка:</b> специалист может разметить маску и сопоставить её с маской алгоритма.</li>
</ul><p>Эти пункты описывают функции прототипа. Они сами по себе не подтверждают качество подсчёта или медицинскую точность.</p></section>
<section><h2>Лабораторные показатели</h2><p>Для лабораторного скрининга пользователь вносит Hb из общего анализа крови или проверяет распознанные OCR поля. Сайт сравнивает Hb с выбранным порогом и отдельно описывает введённые индексы. Экспериментальная CBC-модель не показывается как вероятность анемии. Микрофотография мазка не заменяет значение гемоглобина.</p><p>Учебные опыты используют цифровую обработку изображения и синтетические примеры. Они не измеряют гемоглобин, клиническую оптику или вероятность заболевания.</p></section>
<section><h2>План экспериментальной проверки</h2><ol><li>Согласовать критерии ручной разметки и подготовить реальные кадры с разрешением на использование.</li><li>Разделить набор по пациентам и мазкам до настройки алгоритма.</li><li>Попросить двух наблюдателей независимо разметить одинаковые кадры.</li><li>Сравнить контуры и подсчёт с эталоном, указать метрики и ошибки.</li><li>Проверить итог на снимках другого микроскопа или набора данных.</li></ol><p>Публичные ресурсы для планирования исследования: <a href="https://doi.org/10.5281/zenodo.7801430" target="_blank" rel="noopener">RedTell DSE</a> · <a href="https://data.mendeley.com/datasets/hms3sjzt7f/1" target="_blank" rel="noopener">AneRBC</a> · <a href="https://doi.org/10.6084/m9.figshare.13053968" target="_blank" rel="noopener">Expert Annotated RBC</a> · <a href="https://github.com/Shenggan/BCCD_Dataset" target="_blank" rel="noopener">BCCD</a>. Перед применением следует проверить лицензию и соответствие набора задаче.</p></section>
<section><h2>Границы проекта</h2><p>CellVision — учебно-исследовательский прототип. Он не ставит диагноз, не заменяет лабораторный анализ или специалиста. Точность сегментации и классификации требует дальнейшей независимой оценки; межэкспертное согласие можно сообщать только после независимой разметки одних и тех же изображений несколькими наблюдателями.</p></section>
<footer><a href="/#research">Вернуться к разделу исследования ↑</a> · CellVision</footer></main></body></html>'''
evidence.write_text(evidence_html, encoding="utf-8")

# Remove experimental anemia-probability inference from the user-facing backend.
server = root / "web_app.py"
py = server.read_text(encoding="utf-8")
py = py.replace('IMAGE_MODEL_PATH = os.path.join(MODEL_DIR, "anemia_image_svm.npz")\nCBC_MODEL_PATH = os.path.join(MODEL_DIR, "cbc_anemia_logistic.npz")\n', '')
py, count = re.subn(r'def load_image_model\(\):.*?(?=def cbc_pattern\()', '', py, count=1, flags=re.S)
if count != 1:
    raise SystemExit("Could not retire CBC/photo probability functions")
screen_stub = '''def image_screen(image):
    """Describe the image-analysis scope without returning an anemia score."""
    return {"status": "visualization_only", "label": "Исследовательская визуализация",
            "detail": "Изображение используется для визуализации сегментированных объектов и морфологии. Вероятность анемии по фото не рассчитывается."}


'''
py = re.sub(r'(?=def cbc_pattern\()', lambda _: screen_stub, py, count=1)
py = py.replace('IMAGE_MODEL, IMAGE_CLASSES, IMAGE_PLATT_A, IMAGE_PLATT_B = None, [], 0.0, 0.0\nCBC_MODEL = None\n', '')
py = py.replace('''            "whole_smear_trained": IMAGE_MODEL is not None, "whole_smear_classes": IMAGE_CLASSES,
            "cbc_probability_trained": CBC_MODEL is not None})''', '''            "whole_smear_trained": False, "whole_smear_classes": [],
            "cbc_probability_trained": False})''')
py = py.replace('                assessment["cbc_probability"] = cbc_probability(cbc, data.get("age"), population)\n', '')
py = py.replace('                cbc_risk = cbc_probability(data.get("cbc", {}), data.get("age"), population)\n', '')
py = py.replace('                assessment["cbc_probability"] = cbc_risk\n', '')
py = py.replace('"cbc_patterns":cbc_summary,"cbc_probability":cbc_risk,"image_screen":image_result,', '"cbc_patterns":cbc_summary,"image_screen":image_result,')
py = py.replace('    IMAGE_MODEL, IMAGE_CLASSES, IMAGE_PLATT_A, IMAGE_PLATT_B = load_image_model()\n    CBC_MODEL = load_cbc_model()\n', '')
server.write_text(py, encoding="utf-8")

print("Updated research UI copy, removed unsupported probability displays and public metric panels.")
