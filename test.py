from fpdf import FPDF
import os
folder = os.getcwd()

# Create a sample resume PDF without "programming" or "coding"
resume_text = """programming"""

pdf = FPDF()
pdf.add_page()
pdf.set_font("Arial", size=12)
for line in resume_text.split("\n"):
    pdf.multi_cell(0, 10, line)

resume_path = os.path.join(folder,"resume.pdf")
pdf.output(resume_path)

# Create a sample JD text file that includes "programming" and "coding"
jd_text = """coding"""

jdpath = os.path.join(folder,"jd.txt")
with open(jdpath, "w") as f:
    f.write(jd_text)

resume_path, jdpath
