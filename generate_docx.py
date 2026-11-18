import docx
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn


def set_cell_background(cell, hex_color):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'), hex_color)
    tcPr.append(shd)


def create_document():
    doc = docx.Document()

    # Page Margins
    for section in doc.sections:
        section.top_margin = Inches(0.8)
        section.bottom_margin = Inches(0.8)
        section.left_margin = Inches(0.8)
        section.right_margin = Inches(0.8)

    # Styles
    title_p = doc.add_paragraph()
    title_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run_title = title_p.add_run("AISD — IT Incident Management System")
    run_title.font.name = "Arial"
    run_title.font.size = Pt(22)
    run_title.font.bold = True
    run_title.font.color.rgb = RGBColor(2, 132, 199) # Sky Blue

    sub_p = doc.add_paragraph()
    sub_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run_sub = sub_p.add_run("Team Member Execution Guide & Demonstration Walkthrough")
    run_sub.font.name = "Arial"
    run_sub.font.size = Pt(13)
    run_sub.font.color.rgb = RGBColor(71, 85, 105)

    doc.add_paragraph().paragraph_format.space_after = Pt(10)

    # Section 1: Overview
    h1 = doc.add_heading("1. Quick Start (1-Click Automated Setup)", level=1)
    h1.runs[0].font.color.rgb = RGBColor(15, 23, 42)

    p1 = doc.add_paragraph(
        "To run the complete system on any Windows laptop without complicated manual configuration, follow these 3 steps:"
    )
    p1.runs[0].font.name = "Arial"

    steps = [
        ("Step 1: Extract Files", "Unzip AISD_PROJECT.zip to any folder on your laptop (e.g. C:\\Projects\\AISD or Desktop\\AISD)."),
        ("Step 2: Double-Click Installer", "Double-click the file named SETUP_AND_RUN.bat in the root folder."),
        ("Step 3: Automated Launch", "The script automatically validates Python/Node.js, installs dependencies, launches the FastAPI backend and Next.js portal, and opens http://localhost:3000 in your browser.")
    ]

    for title, desc in steps:
        p = doc.add_paragraph(style='List Bullet')
        r_b = p.add_run(f"{title}: ")
        r_b.bold = True
        r_b.font.name = "Arial"
        r_d = p.add_run(desc)
        r_d.font.name = "Arial"

    p_note = doc.add_paragraph()
    r_note = p_note.add_run("Tip: After the initial setup, you can simply double-click RUN_AISD.bat anytime to launch everything instantly in under 3 seconds!")
    r_note.italic = True
    r_note.font.color.rgb = RGBColor(3, 105, 161)

    # Section 2: Prerequisites
    doc.add_heading("2. System Prerequisites", level=1)
    doc.add_paragraph("Ensure the target PC has the following standard tools installed:")
    
    prereqs = [
        ("Python 3.10+", "Download from python.org. Check 'Add Python to PATH' during installation."),
        ("Node.js 18+ (LTS)", "Download from nodejs.org."),
        ("Ollama (Optional)", "If installed with qwen3.5:4b, central AI diagnosis uses it. If Ollama is NOT installed, AISD automatically falls back to deterministic rules with zero errors.")
    ]
    for name, desc in prereqs:
        p = doc.add_paragraph(style='List Bullet')
        r_name = p.add_run(f"{name}: ")
        r_name.bold = True
        p.add_run(desc)

    # Section 3: Login Accounts
    doc.add_heading("3. Default Demo Accounts (Auto-Seeded)", level=1)
    doc.add_paragraph("The database seeds automatically on startup with three test roles:")

    table = doc.add_table(rows=1, cols=4)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.style = 'Table Grid'
    hdr = table.rows[0].cells
    hdr[0].text = "Role"
    hdr[1].text = "Email"
    hdr[2].text = "Password"
    hdr[3].text = "Capabilities"

    for c in hdr:
        set_cell_background(c, "0284C7")
        c.paragraphs[0].runs[0].font.bold = True
        c.paragraphs[0].runs[0].font.color.rgb = RGBColor(255, 255, 255)

    data = [
        ("Technician", "tech@college.edu", "Tech@123", "Inspect evidence, run AI diagnosis, approve/reject plans, execute repairs, verify postconditions."),
        ("Student", "student@college.edu", "Student@123", "Report incidents, track ticket progress, view verified resolution summaries."),
        ("Administrator", "admin@college.edu", "Admin@123", "Full access, manage knowledge base SOPs, policy settings, audit event logs, and endpoint fleet.")
    ]

    for role, email, pwd, caps in data:
        row = table.add_row().cells
        row[0].text = role
        row[0].paragraphs[0].runs[0].font.bold = True
        row[1].text = email
        row[2].text = pwd
        row[3].text = caps

    # Section 4: Demo Scenario
    doc.add_heading("4. How to Demonstrate to Evaluators (The Wi-Fi Scenario)", level=1)
    doc.add_paragraph(
        "Demonstrate the complete closed-loop workflow: "
        "Report -> Diagnose -> Retrieve SOP -> Plan -> Authorize -> Execute -> Verify -> Resolve."
    )

    demo_steps = [
        "1. Open http://localhost:3000/login and click the 'Technician' quick sign-in button.",
        "2. Go to the 'Incidents' tab and click on ticket INC-20261104-1001: 'My laptop is connected to the college Wi-Fi, but I cannot access anything.'",
        "3. Click 'Run Ollama Diagnosis'. Point out the 95% confidence hypothesis on DHCP Lease Failure (APIPA 169.254 address) and the cited SOP KB-NET-001.",
        "4. Click 'Propose Tool: renew_dhcp'. Explain that safety policy flags this tool as Risk Level R2, requiring technician approval.",
        "5. Click 'Authorize / Approve' as the technician.",
        "6. Click 'Execute Remediation & Verify Postcondition'.",
        "7. Point out the postcondition check: valid IP assigned (10.12.4.152), gateway ping verified (3.8 ms), and the incident status automatically transitions to RESOLVED!"
    ]
    for s in demo_steps:
        doc.add_paragraph(s)

    # Section 5: Automated script
    doc.add_heading("5. 1-Click Automated Terminal Demo", level=1)
    doc.add_paragraph("You can also run the complete scenario in terminal in under 5 seconds:")
    p_code = doc.add_paragraph()
    r_code = p_code.add_run("python aisd\\scripts\\run_demo.py")
    r_code.font.name = "Consolas"
    r_code.font.bold = True
    r_code.font.color.rgb = RGBColor(16, 185, 129)

    # Save
    out_path = "AISD_TEAM_RUN_GUIDE.docx"
    doc.save(out_path)
    print(f"Generated {out_path}")


if __name__ == "__main__":
    create_document()
