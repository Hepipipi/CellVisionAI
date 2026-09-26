# import math
import os
import cv2
import customtkinter as ctk
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from PIL import Image, ImageTk
import numpy as np
import pandas as pd

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")


class CellVisionApp(ctk.CTk):

  def __init__(self):
    super().__init__()
    self.title("CellVision AI — Digital Pathology & Cell Morphology MVP")
    self.geometry("1200x780")


    self.current_img = None
    self.processed_img = None
    self.cell_areas = []


    self.lbl_title = ctk.CTkLabel(
        self,
        text=(
            "CellVision AI: Компьютерная микроскопия и анализ морфологии"
            " эритроцитов"
        ),
        font=("Arial", 22, "bold"),
    )
    self.lbl_title.pack(pady=10)


    self.main_container = ctk.CTkFrame(self)
    self.main_container.pack(fill="both", expand=True, padx=15, pady=10)


    self.left_panel = ctk.CTkFrame(self.main_container, width=320)
    self.left_panel.pack(side="left", fill="y", padx=10, pady=10)

    self.btn_gen_sample = ctk.CTkButton(
        self.left_panel,
        text="🧪 Сгенерировать микропрепарат",
        command=self.generate_synthetic_blood_sample,
    )
    self.btn_gen_sample.pack(pady=10, padx=15, fill="x")

    self.btn_load = ctk.CTkButton(
        self.left_panel,
        text="📁 Загрузить снимок мазка крови",
        command=self.load_image,
    )
    self.btn_load.pack(pady=5, padx=15, fill="x")

    self.btn_analyze = ctk.CTkButton(
        self.left_panel,
        text="🔬 Запустить анализ (Watershed)",
        command=self.analyze_cells,
        fg_color="#1f538d",
    )
    self.btn_analyze.pack(pady=15, padx=15, fill="x")

    self.lbl_log = ctk.CTkLabel(
        self.left_panel, text="Результаты анализа:", font=("Arial", 14, "bold")
    )
    self.lbl_log.pack(pady=5, padx=15, anchor="w")

    self.log_box = ctk.CTkTextbox(
        self.left_panel, width=290, height=380, font=("Consolas", 11)
    )
    self.log_box.pack(pady=5, padx=15, fill="both", expand=True)


    self.right_panel = ctk.CTkFrame(self.main_container)
    self.right_panel.pack(
        side="right", fill="both", expand=True, padx=10, pady=10
    )


    self.img_frame = ctk.CTkFrame(self.right_panel)
    self.img_frame.pack(fill="both", expand=True, padx=5, pady=5)

    self.lbl_orig_title = ctk.CTkLabel(
        self.img_frame, text="Исходный микропрепарат", font=("Arial", 12)
    )
    self.lbl_orig_title.grid(row=0, column=0, padx=10, pady=2)

    self.lbl_seg_title = ctk.CTkLabel(
        self.img_frame,
        text="Сегментация клеток (Watershed)",
        font=("Arial", 12),
    )
    self.lbl_seg_title.grid(row=0, column=1, padx=10, pady=2)

    self.lbl_orig_img = ctk.CTkLabel(
        self.img_frame, text="[Нет изображения]", width=380, height=260
    )
    self.lbl_orig_img.grid(row=1, column=0, padx=10, pady=5)

    self.lbl_seg_img = ctk.CTkLabel(
        self.img_frame, text="[Ожидание анализа]", width=380, height=260
    )
    self.lbl_seg_img.grid(row=1, column=1, padx=10, pady=5)


    self.chart_frame = ctk.CTkFrame(self.right_panel, height=220)
    self.chart_frame.pack(fill="x", padx=5, pady=5)

    self.log(
        "Система готова к работе.\nЗагрузите фото или нажмите 'Сгенерировать"
        " микропрепарат'."
    )

  def log(self, text):
    self.log_box.insert("end", f"{text}\n")
    self.log_box.see("end")

  def generate_synthetic_blood_sample(self):

    img_size = (600, 800, 3)

    bg = np.ones(img_size, dtype=np.uint8) * 235
    bg[:, :, 0] = 230

    np.random.seed(42)
    num_cells = 65

    for _ in range(num_cells):
      cx = np.random.randint(50, 750)
      cy = np.random.randint(50, 550)
      radius = np.random.randint(22, 32)


      cv2.circle(bg, (cx, cy), radius, (180, 50, 80), -1)
      cv2.circle(
          bg, (cx, cy), int(radius * 0.5), (220, 120, 140), -1
      )


    bg = cv2.GaussianBlur(bg, (5, 5), 0)
    noise = np.random.normal(0, 5, bg.shape).astype(np.uint8)
    bg = cv2.add(bg, noise)

    cv2.imwrite("sample_blood.png", bg)
    self.load_image_from_path("sample_blood.png")
    self.log(
        "🧪 Сгенерирован тестовый микропрепарат с перекрывающимися эритроцитами."
    )

  def load_image(self):
    file_path = ctk.filedialog.askopenfilename(
        filetypes=[("Image Files", "*.png *.jpg *.jpeg *.bmp")]
    )
    if file_path:
      self.load_image_from_path(file_path)

  def load_image_from_path(self, path):
    self.current_img = cv2.imread(path)
    img_rgb = cv2.cvtColor(self.current_img, cv2.COLOR_BGR2RGB)

    pil_img = Image.fromarray(img_rgb).resize((380, 260))
    tk_img = ImageTk.PhotoImage(pil_img)

    self.lbl_orig_img.configure(image=tk_img, text="")
    self.lbl_orig_img.image = tk_img
    self.log(f"Загружен файл: {os.path.basename(path)}")

  def analyze_cells(self):
    if self.current_img is None:
      self.log("⚠️ Ошибка: Сначала загрузите изображение!")
      return

    img = self.current_img.copy()
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    _, thresh = cv2.threshold(
        blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
    )


    kernel = np.ones((3, 3), np.uint8)
    opening = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel, iterations=2)


    dist_transform = cv2.distanceTransform(opening, cv2.DIST_L2, 5)
    _, sure_fg = cv2.threshold(
        dist_transform, 0.35 * dist_transform.max(), 255, 0
    )

    sure_fg = np.uint8(sure_fg)
    unknown = cv2.subtract(opening, sure_fg)


    _, markers = cv2.connectedComponents(sure_fg)
    markers = markers + 1
    markers[unknown == 255] = 0

    markers = cv2.watershed(img, markers)


    img_out = img.copy()
    img_out[markers == -1] = [0, 255, 0]  # Зеленые границы маркеров

    unique_labels = np.unique(markers)
    self.cell_areas = []

    for label in unique_labels:
      if label <= 1:  # Фон и неизвестная зона
        continue

      mask = np.uint8(markers == label)
      cnts, _ = cv2.findContours(
          mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
      )

      if cnts:
        area = cv2.contourArea(cnts[0])
        if area > 100:
          self.cell_areas.append(area)


          M = cv2.moments(cnts[0])
          if M["m00"] != 0:
            cx = int(M["m10"] / M["m00"])
            cy = int(M["m01"] / M["m00"])
            cv2.circle(img_out, (cx, cy), 3, (0, 0, 255), -1)


    seg_rgb = cv2.cvtColor(img_out, cv2.COLOR_BGR2RGB)
    pil_seg = Image.fromarray(seg_rgb).resize((380, 260))
    tk_seg = ImageTk.PhotoImage(pil_seg)

    self.lbl_seg_img.configure(image=tk_seg, text="")
    self.lbl_seg_img.image = tk_seg


    self.compute_clinical_metrics()
    self.plot_histogram()

  def compute_clinical_metrics(self):
    total_cells = len(self.cell_areas)
    if total_cells == 0:
      self.log("⚠️ Клетки не распознаны.")
      return

    mean_area = np.mean(self.cell_areas)
    std_area = np.std(self.cell_areas)
    rdw = (std_area / mean_area) * 100

    self.log_box.delete("1.0", "end")
    self.log("=== ОТЧЕТ МОРФОМЕТРИИ ===")
    self.log(f"Распознано клеток: {total_cells} шт.")
    self.log(f"Ср. площадь (MCV): {mean_area:.1f} px²")
    self.log(f"Отклонение (Std): {std_area:.1f}")
    self.log(f"Индекс RDW: {rdw:.2f}%")
    self.log("------------------------")

    if rdw > 14.5:
      self.log("⚠️ ДИАГНОЗ: Зафиксирован высокий анизоцитоз (RDW > 14.5%).")
      self.log("Высокий риск анемии!")
    else:
      self.log("✅ ДИАГНОЗ: Морфология в норме (Нормоцитоз).")

  def plot_histogram(self):

    for widget in self.chart_frame.winfo_children():
      widget.destroy()

    fig, ax = plt.subplots(figsize=(5, 2.2), dpi=100)
    fig.patch.set_facecolor("#2b2b2b")
    ax.set_facecolor("#1e1e1e")

    ax.hist(
        self.cell_areas,
        bins=15,
        color="#3a7ebf",
        edgecolor="white",
        alpha=0.8,
    )
    ax.set_title(
        "Распределение объемов эритроцитов (RDW Profile)",
        color="white",
        fontsize=10,
    )
    ax.tick_params(colors="white", labelsize=8)
    ax.spines["bottom"].set_color("white")
    ax.spines["left"].set_color("white")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    canvas = FigureCanvasTkAgg(fig, master=self.chart_frame)
    canvas.draw()
    canvas.get_tk_widget().pack(fill="both", expand=True)


if __name__ == "__main__":
  app = CellVisionApp()
  app.mainloop()