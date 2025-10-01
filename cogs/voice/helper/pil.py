import matplotlib.pyplot as plt
import io

import matplotlib.dates as mdates
import matplotlib.font_manager as fm
import numpy as np


from datetime import datetime

from PIL import Image, ImageDraw, ImageFont
from io import BytesIO

import requests

def format_total_time(seconds: int):
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    seconds = seconds % 60
    return f"{hours} jam, {minutes} menit, {seconds} detik"

def create_welcome_card(username: str, avatar_url: str) -> BytesIO:
    # Load avatar image
    try:
        response = requests.get(avatar_url)
        response.raise_for_status()
        avatar = Image.open(BytesIO(response.content)).convert("RGBA").resize((256, 256))
    except Exception as e:
        avatar = Image.new("RGBA", (256, 256), (255, 255, 255, 0))  # Placeholder kosong

    # Create circular mask for avatar
    mask = Image.new('L', (256, 256), 0)
    draw_mask = ImageDraw.Draw(mask)
    draw_mask.ellipse((0, 0, 255, 255), fill=255)

    # Membuat border putih untuk avatar
    border = Image.new('RGBA', (256, 256), (0, 0, 0, 0))
    draw_border = ImageDraw.Draw(border)
    draw_border.ellipse((0, 0, 255, 255), outline="white", width=10)

    # Load background image
    background_path = "utils/data/bg/bg-welcome.png"
    try:
        card = Image.open(background_path).convert("RGBA")
    except FileNotFoundError:
        card = Image.new("RGBA", (800, 400), (0, 0, 0, 0))  # Default fallback size
    draw = ImageDraw.Draw(card)

    # Load fonts
    font_title = "utils/data/font/Rockybilly.ttf"
    font_text = "utils/data/font/BreeSerif-Regular.ttf"

    # Welcome font tetap di 60
    try:
        welcome_font = ImageFont.truetype(font_title, 60)
    except IOError:
        welcome_font = ImageFont.load_default()

    # Username font dinamis berdasarkan panjang karakter
    if len(username) <= 15:
        username_font_size = 30
    elif len(username) <= 20:
        username_font_size = 25
    elif len(username) <= 25:
        username_font_size = 20
    else:
        username_font_size = 15

    try:
        username_font = ImageFont.truetype(font_text, username_font_size)
    except IOError:
        username_font = ImageFont.load_default()

    # Posisi avatar di sebelah kanan (disesuaikan dengan ukuran background)
    avatar_x = card.width - 256 - 45  # 40px dari kanan
    card.paste(avatar, (avatar_x, 50), mask)
    card.paste(border, (avatar_x, 50), border)

    # Efek teks dengan bayangan
    shadow_color = (0, 0, 0, 200)
    main_color = (255, 255, 255)

    # Text "WELCOME" dengan efek bayangan
    welcome_text = "Welcome"
    welcome_position = (90, 40)  # Posisi kiri atas
    draw.text((welcome_position[0]+2, welcome_position[1]+2), welcome_text, font=welcome_font, fill=shadow_color)
    draw.text(welcome_position, welcome_text, font=welcome_font, fill=main_color)

    # Username text
    username_position = (215, 220)  # Sesuai posisi lama
    draw.text((username_position[0] + 2, username_position[1] + 2), username, font=username_font, fill=shadow_color)
    draw.text(username_position, username, font=username_font, fill=main_color)

    # Simpan ke BytesIO
    output = BytesIO()
    card.save(output, format="PNG")
    output.seek(0)
    return output

def create_daily_stats_card(username: str, avatar_url: str, total_time: int) -> BytesIO:
    # Load avatar image
    response = requests.get(avatar_url)
    avatar = Image.open(BytesIO(response.content)).convert("RGBA").resize((256, 256))
    
    # Create circular mask for avatar
    mask = Image.new('L', (256, 256), 0)
    draw_mask = ImageDraw.Draw(mask)
    draw_mask.ellipse((0, 0, 255, 255), fill=255)  # Membuat mask lingkaran
    
    # Membuat border putih untuk avatar
    border = Image.new('RGBA', (256, 256), (0, 0, 0, 0))
    draw_border = ImageDraw.Draw(border)
    draw_border.ellipse((0, 0, 255, 255), outline="white", width=10)

    # Load background image
    background_path = "utils/data/bg/bg-mydaily.png"
    card = Image.open(background_path).convert("RGBA")
    draw = ImageDraw.Draw(card)

    # Load fonts
    font_title = "utils/data/font/BreeSerif-Regular.ttf"
    font_text = "utils/data/font/BreeSerif-Regular.ttf"
    
    # Determine title font size based on username length
    base_title_size = 65
    if len(username) > 15:  # If more than 15 characters
        title_size = base_title_size - 10
    elif len(username) > 10:  # If more than 10 characters
        title_size = base_title_size - 5
    elif len(username) > 5:  # If more than 5 characters
        title_size = base_title_size - 3
    else:
        title_size = base_title_size
    
    title_font = ImageFont.truetype(font_title, title_size)
    text_font = ImageFont.truetype(font_text, 25)
    title_medium = ImageFont.truetype(font_title, 31)

    # Tempelkan avatar dengan mask lingkaran dan border
    card.paste(avatar, (40, 50), mask)
    card.paste(border, (40, 50), border)

    # Efek teks dengan bayangan
    text_position = (320, 80)
    shadow_color = (0, 0, 0, 200)
    main_color = (255, 255, 255)
    
    # Username dengan efek bayangan
    draw.text((text_position[0]+1, text_position[1]+1), f"{username}", font=title_font, fill=shadow_color)
    draw.text(text_position, f"{username}", font=title_font, fill=main_color)

    # Voice time text dengan efek bayangan
    vt_text = "Voice Time :"
    vt_position = (320, 185)
    draw.text((vt_position[0]+1, vt_position[1]+1), vt_text, font=text_font, fill=shadow_color)
    draw.text(vt_position, vt_text, font=text_font, fill=(200, 200, 200))

    # Voice time value dengan efek bayangan
    vt_value = format_total_time(total_time)
    vt_value_position = (320, 220)
    draw.text((vt_value_position[0]+1, vt_value_position[1]+1), vt_value, font=title_medium, fill=shadow_color)
    draw.text(vt_value_position, vt_value, font=title_medium, fill=main_color)

    # Simpan ke BytesIO
    output = BytesIO()
    card.save(output, format="PNG")
    output.seek(0)
    return output

def create_topfriends_card(
    formatted_friends: list[dict],
    target_avatar_url: str,
    target_name: str,
    total_time
) -> BytesIO:

    font_path="utils/data/font/Poppins-Bold.ttf"
    regular_path="utils/data/font/Poppins-Regular.ttf"
    uname_font_path="utils/data/font/Poppins-Bold.ttf"
    background_path="utils/data/bg/bg-topfriends-new.png"

    # 1. Load background langsung, tanpa resize
    card = Image.open(background_path).convert("RGBA")
    draw = ImageDraw.Draw(card)

    # 2. Avatar Layout (Persegi dengan Rounded Avatar dan Border Putih)
    av_size = 250
    x_av = 550
    y_av = 34

    # Ambil avatar dari URL
    resp = requests.get(target_avatar_url)
    avatar = Image.open(BytesIO(resp.content)).convert("RGBA").resize((av_size, av_size), Image.LANCZOS)

    # Buat masking rounded
    corner_radius = 20
    mask = Image.new('L', (av_size, av_size), 0)
    draw_mask = ImageDraw.Draw(mask)
    draw_mask.rounded_rectangle(
        [0, 0, av_size, av_size],
        radius=corner_radius,
        fill=255
    )

    # Siapkan tempat tempelan avatar dengan masking
    rounded_avatar = Image.new("RGBA", (av_size, av_size))
    rounded_avatar.paste(avatar, (0, 0), mask)

    # Tempel ke background
    card.paste(rounded_avatar, (x_av, y_av), rounded_avatar)

    # Gambar border putih
    border_thickness = 6
    draw = ImageDraw.Draw(card)
    draw.rounded_rectangle(
        [
            x_av - border_thickness // 2,
            y_av - border_thickness // 2,
            x_av + av_size + border_thickness // 2,
            y_av + av_size + border_thickness // 2
        ],
        radius=corner_radius,
        outline="white",
        width=border_thickness
    )

    # Tetap pakai ini untuk ambil warna
    custom_colors_hex = ['#03bcd6', '#014d86', '#ffffff', '#3d4d60']
    chart_size = 2.8
    donut_thickness = 0.35

    filtered_friends = [fr for fr in formatted_friends if fr["percent"] > 0]
    sizes = [fr["percent"] for fr in filtered_friends]
    colors = [tuple(int(h[i:i+2], 16)/255 for i in (1, 3, 5)) for h in custom_colors_hex[:len(sizes)]]

    fig, ax = plt.subplots(figsize=(chart_size, chart_size), dpi=100)

    # Buat pie tanpa autopct
    wedges, _ = ax.pie(
        sizes,
        labels=None,
        startangle=90,
        colors=colors,
        wedgeprops=dict(width=donut_thickness)
    )

    # Tambahkan label persentase manual lebih jauh dari lingkaran
    for i, w in enumerate(wedges):
        ang = (w.theta2 + w.theta1) / 2
        radius = 1.25  
        x = radius * np.cos(np.deg2rad(ang))
        y = radius * np.sin(np.deg2rad(ang))

        if sizes[i] >= 5:
            ax.text(x, y, f"{sizes[i]:.0f}%", ha='center', va='center',
                    fontsize=11, fontweight='bold', color='white')

    ax.axis('equal')


    buf = BytesIO()
    plt.savefig(buf, format='PNG', transparent=True, pad_inches=0)


    buf.seek(0)
    donut_img = Image.open(buf).convert("RGBA")
    plt.close(fig)

    donut_img = donut_img.resize((270, 270), Image.LANCZOS)
    card.paste(donut_img, (560, 325), donut_img)

    # Fonts
    uname_font = ImageFont.truetype(uname_font_path, 65)
    topfriend_list_font  = ImageFont.truetype(font_path, 20)
    med_font   = ImageFont.truetype(font_path, 31)

    shadow = (0, 0, 0, 200)
    white  = (255, 255, 255, 255)
    grey   = (200, 200, 200, 255)

    # Username position
    name_length = len(target_name)
    if name_length >= 15:
        x_name, y_name = 75, 130
        size = 45 - (name_length - 12) * 2
    elif name_length >= 12:
        x_name, y_name = 90, 120
        size = 50 - (name_length - 12) * 2
    elif name_length >= 7:
        x_name, y_name = 100, 110
        size = 60 - max(0, name_length - 10) * 2
    else:
        x_name, y_name = 100, 90
        size = 90 - max(0, name_length - 10) * 2


    uname_font = ImageFont.truetype(uname_font_path, size)
    draw.text((x_name + 1, y_name + 1), target_name, font=uname_font, fill=shadow)
    draw.text((x_name,     y_name    ), target_name, font=uname_font, fill=white)

    # Top friends text
    list_name_font = ImageFont.truetype(font_path, 20)
    time_font      = ImageFont.truetype(regular_path, 16)
    positions = [
        {"name": (130, 419), "label": (130, 446)},
        {"name": (130, 485), "label": (130, 512)},
        {"name": (130, 555), "label": (130, 584)},
        {"name": (130, 622), "label": (130, 649)},
    ]

    for idx, fr in enumerate(formatted_friends[:4]):
        pos = positions[idx]
        index_and_name = f"{fr['name']}"
        draw.text((pos["name"][0]+1, pos["name"][1]+1), index_and_name, font=list_name_font, fill=shadow)
        draw.text((pos["name"][0],   pos["name"][1]),   index_and_name, font=list_name_font, fill=white)

        voice_line = f"Total Voice: {fr['total_time_str']}"
        draw.text((pos["label"][0], pos["label"][1]), voice_line, font=time_font, fill=white)

    font_total = ImageFont.truetype(font_path, 24)
    draw.text((63 + 1, 330 + 1), total_time, font=font_total, fill=shadow)
    draw.text((63, 330), total_time, font=font_total, fill=white)

    out = BytesIO()
    card.save(out, format="PNG")
    out.seek(0)
    return out


def multiline_date(x, pos):
    dt = mdates.num2date(x)
    return f"{dt.strftime('%b')}\n{dt.day}"

def summary_format(vc_summary: dict) -> dict:
    if not vc_summary:
        return {
            "sum": "-",
            "avg": "-",
            "min": "-",
            "max": "-"
        }

    formatted = {
        "sum": vc_summary["sum"],
        "avg": round(vc_summary["avg"], 1) if vc_summary["avg"] else 0,
        "min": f"{vc_summary['min_date'].strftime('%d %b')} ( {vc_summary['min']} )" if vc_summary["min_date"] else "-",
        "max": f"{vc_summary['max_date'].strftime('%d %b')} ( {vc_summary['max']} )" if vc_summary["max_date"] else "-"
    }

    return formatted

def draw_vc_summary_section(draw, vc_summary: dict, base_x: int = 60, base_y: int = 680, spacing_x: int = 150):
    """
    Gambar HANYA NILAI vc_summary (tanpa label Min/Max/Sum/Avg).
    """
    vc_data = summary_format(vc_summary)
    text_color = "#14202a"  # ← warna teks yang diminta

    value_font = ImageFont.truetype("utils/data/font/Poppins-Bold.ttf", size=11)

    keys = ["min", "max", "sum", "avg"]

    for i, key in enumerate(keys):
        x = base_x + (len(keys) - 1 - i) * spacing_x

        # Tambahkan offset khusus untuk 'min'
        if key == "min":
            x += 35  # atau sesuaikan angka ini sampai pas
        draw.text((x, base_y), f"{vc_data[key]}", font=value_font, fill=text_color)

def generate_dual_chart_card(
    avatar_url,
    guild_name,
    total_member,
    guild_since:str,
    user_data: list[tuple[str, int]],
    traffic_data: list[tuple[str, int]],
    vc_summary,
    vt_summary
) -> io.BytesIO:
    
    
    # Kumpulkan Data
    dates1 = [datetime.strptime(d[0], "%Y-%m-%d").date() for d in user_data]
    values1 = [d[1] for d in user_data]

    dates2 = [datetime.strptime(d[0], "%Y-%m-%d").date() for d in traffic_data]
    values2 = [d[1] for d in traffic_data]

    # Font settings
    axis_font_path = "utils/data/font/Poppins-Regular.ttf"
    guild_name_font = "utils/data/font/Poppins-Bold.ttf"
    axis_font_prop = fm.FontProperties(fname=axis_font_path, size=8)  # ← [❶] kecilkan font

    # Buat figure tunggal
    fig, ax = plt.subplots(figsize=(7, 3.5))

    # Plot data 1 - Voice User (Hijau)
    ax.fill_between(dates1, values1, color="#4CAF50", alpha=0.3)
    ax.plot(dates1, values1, color="#388E3C", linewidth=2, marker="o")

    markerline, stemlines, baseline = ax.stem(
        dates1, values1,
        linefmt="#2E7D32", markerfmt="o", basefmt=" "
    )

    plt.setp(markerline, color="#2E7D32")
    plt.setp(stemlines, color="#2E7D32")

    # Plot data 2 - Join/Leave (Biru)
    ax.fill_between(dates2, values2, color="#2196F3", alpha=0.2)
    ax.plot(dates2, values2, color="#1976D2", linewidth=2, marker="o")

    # Format tanggal
    ax.xaxis.set_major_formatter(plt.FuncFormatter(multiline_date))
    
    plt.setp(
        ax.xaxis.get_majorticklabels(),
        fontproperties=axis_font_prop,
        ha="center",
        color="white"  # ← 🟩 FONT LABEL PUTIH
    )
    plt.setp(
        ax.yaxis.get_majorticklabels(),
        fontproperties=axis_font_prop,
        color="white"  # ← 🟩 FONT LABEL Y-AXIS PUTIH
    )

    ax.spines['bottom'].set_color("white")
    ax.spines['left'].set_color("white")
    ax.spines['top'].set_color("white")
    ax.spines['right'].set_color("white")
    ax.tick_params(axis='x', colors='white')
    ax.tick_params(axis='y', colors='white')

    ax.grid(True, linestyle="--", alpha=0.3)

    # Simpan ke buffer PNG transparan
    buf = io.BytesIO()
    plt.tight_layout()
    plt.savefig(buf, format="png", transparent=True)
    plt.close()
    buf.seek(0)

    # Tempel ke background
    bg = Image.open("utils/data/bg/bg-statistic.png").convert("RGBA")
    chart_img = Image.open(buf).convert("RGBA")

    chart_img = chart_img.resize((650, 270))  # ← [❸] perkecil chart

    bg_width, _ = bg.size
    # pos_x = (bg_width - chart_img.width) // 2
    pos_x = 60
    pos_y = 310  # ← [❹] turunkan posisi chart

    # 2. Avatar Layout (Persegi dengan Rounded Avatar dan Border Putih)
    av_size = 200
    x_av = 60
    y_av = 30

    # Ambil avatar dari URL
    resp = requests.get(avatar_url)
    avatar = Image.open(BytesIO(resp.content)).convert("RGBA").resize((av_size, av_size), Image.LANCZOS)

    # Buat masking rounded
    corner_radius = 20
    mask = Image.new('L', (av_size, av_size), 0)
    draw_mask = ImageDraw.Draw(mask)
    draw_mask.rounded_rectangle(
        [0, 0, av_size, av_size],
        radius=corner_radius,
        fill=255
    )

    # Siapkan tempat tempelan avatar dengan masking
    rounded_avatar = Image.new("RGBA", (av_size, av_size))
    rounded_avatar.paste(avatar, (0, 0), mask)

    # Tempel ke background
    bg.paste(rounded_avatar, (x_av, y_av), rounded_avatar)

    # Gambar border putih
    border_thickness = 6
    draw = ImageDraw.Draw(bg)
    draw.rounded_rectangle(
        [
            x_av - border_thickness // 2,
            y_av - border_thickness // 2,
            x_av + av_size + border_thickness // 2,
            y_av + av_size + border_thickness // 2
        ],
        radius=corner_radius,
        outline="white",
        width=border_thickness
    )
    
    shadow = (0, 0, 0, 200)
    white  = (255, 255, 255, 255)
    grey   = (200, 200, 200, 255)
    
    # Voice Users Traffic
    draw_vc_summary_section(draw, vc_summary, base_x=123, base_y=652, spacing_x=150)
    # Voice Traffic Summary    
    draw_vc_summary_section(draw, vt_summary, base_x=123, base_y=625, spacing_x=150)


    # Guild name 
    name_length = len(guild_name)

    if name_length < 7:
        # kurang dari 7 karakter
        x_name, y_name = 315, 75
        size = 75 - max(0, name_length - 10) * 2  # tetap pakai logika size shrink jika anomali
    elif name_length > 12:
        # lebih dari 12 karakter → lebih kecil & posisi turun sedikit
        x_name, y_name = 320, 90
        size = 50 - (name_length - 12) * 2
    else:
        # 7 sampai 12 karakter
        x_name, y_name = 325, 85
        size = 60 - max(0, name_length - 10) * 2

    uname_font = ImageFont.truetype(guild_name_font, size)
    draw.text((x_name + 1, y_name + 1), guild_name, font=uname_font, fill=shadow)
    draw.text((x_name,     y_name    ), guild_name, font=uname_font, fill=white)
    
    # 3. Tulisan: Total Member & Guild Since
    x_text = x_av + av_size + 25  
    y_text = pos_y - 90       

    label_font = ImageFont.truetype(axis_font_path, size=15)
    value_font = ImageFont.truetype(guild_name_font, size=15)

    # Total Member
    draw.text((x_text, y_text), "Total Member ", font=label_font, fill=white)
    draw.text((x_text + 110, y_text), f"{total_member}", font=value_font, fill=white)

    # Server Since
    draw.text((x_text, y_text + 30), "Since ", font=label_font, fill=white)
    draw.text((x_text + 45, y_text + 30), guild_since, font=value_font, fill=white)

    
    # 4. Tambahan Label Chart (digeser 70px dari teks sebelumnya)
    chart_label_font = ImageFont.truetype(guild_name_font, size=14)

    # Ganti nilai berikut sampai cocok
    x_du, y_du = 570, 219   # posisi “Daily Users”
    x_dt, y_dt = 570, 250   # posisi “Daily Traffic”

    # Tuliskan teks utama
    draw.text((x_du,     y_du    ), "Daily Traffic",   font=chart_label_font, fill=white)
    draw.text((x_dt,     y_dt    ), "Daily Users", font=chart_label_font, fill=white)



    bg.paste(chart_img, (pos_x, pos_y), chart_img)

    # Simpan final output
    out = io.BytesIO()
    bg.save(out, format="PNG")
    out.seek(0)
    return out

def generate_user_chart_card(
    avatar_url: str,
    username: str,
    user_data: list[tuple[str, int]],        
    session_data: list[tuple[str, int]],     
    time_summary: dict,                      
    session_summary: dict,                   
    join_discord,
    join_server
) -> io.BytesIO:

    # 1. Parse dates & values
    dates1  = [datetime.strptime(d, "%Y-%m-%d").date() for d, _ in user_data]
    values1 = [seconds / 3600 for _, seconds in user_data]      # ← perhatikan unpack

    dates2  = [datetime.strptime(d, "%Y-%m-%d").date() for d, _ in session_data]
    values2 = [count for _, count in session_data]              # sesi tidak dikonversi ke jam

    # 2. Font setup & figure
    axis_font_path   = "utils/data/font/Poppins-Regular.ttf"
    title_font_path  = "utils/data/font/Poppins-Bold.ttf"
    axis_fp = fm.FontProperties(fname=axis_font_path, size=8)
    fig, ax = plt.subplots(figsize=(7, 3.5))

    # --- STYLE CHANGED: gunakan line + fill + stem (sama seperti generate_dual_chart) ---
    # Plot data 1 - Daily Time (Hijau)
    ax.fill_between(dates1, values1, color="#4CAF50", alpha=0.3)
    ax.plot(dates1, values1, color="#388E3C", linewidth=2, marker="o")

    markerline, stemlines, baseline = ax.stem(
        dates1, values1,
        linefmt="#2E7D32", markerfmt="o", basefmt=" "
    )
    plt.setp(markerline, color="#2E7D32")
    plt.setp(stemlines, color="#2E7D32")

    # Plot data 2 - Daily Sessions (Biru)
    ax.fill_between(dates2, values2, color="#2196F3", alpha=0.2)
    ax.plot(dates2, values2, color="#1976D2", linewidth=2, marker="o")
    # --- END STYLE CHANGES ------------------------------------------------------

    ax.xaxis.set_major_formatter(plt.FuncFormatter(multiline_date))  # gunakan fungsi kustom
    plt.setp(ax.xaxis.get_majorticklabels(), fontproperties=axis_fp, ha="center", color="white")
    plt.setp(ax.yaxis.get_majorticklabels(), fontproperties=axis_fp, color="white")
    for spine in ax.spines.values():
        spine.set_color("white")
    ax.tick_params(axis='x', colors='white')
    ax.tick_params(axis='y', colors='white')
    ax.grid(True, linestyle="--", alpha=0.3)

    # 6. Render to transparent buffer
    buf = io.BytesIO()
    plt.tight_layout()
    plt.savefig(buf, format="png", transparent=True)
    plt.close(fig)
    buf.seek(0)

    # 7. Compose on background
    bg = Image.open("utils/data/bg/bg-user-statistic.png").convert("RGBA")
    chart_img = Image.open(buf).convert("RGBA").resize((650, 270))
    bg.paste(chart_img, (60, 310), chart_img)

    # 8. Rounded avatar + border
    resp = requests.get(avatar_url)
    avatar = Image.open(BytesIO(resp.content)).convert("RGBA").resize((200, 200), Image.LANCZOS)
    mask = Image.new('L', (200, 200), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0,0,200,200], radius=20, fill=255)
    rounded = Image.new("RGBA", (200, 200))
    rounded.paste(avatar, (0, 0), mask)
    bg.paste(rounded, (60, 30), rounded)
    d = ImageDraw.Draw(bg)
    d.rounded_rectangle([57,27,263,233], radius=20, outline="white", width=6)

    # 9. Summary sections (reuse your draw_vc_summary_section)
    draw_vc_summary_section(d, time_summary,    base_x=123, base_y=652, spacing_x=150)
    draw_vc_summary_section(d, session_summary, base_x=123, base_y=625, spacing_x=150)

    # 10. Username shadow + text
    shadow = (0,0,0,200); white = (255,255,255,255)
    ln = len(username)
    if ln < 7:
        x_nm, y_nm, sz = 315, 75, 75 - max(0, ln-10)*2
    elif ln > 12:
        x_nm, y_nm, sz = 320, 90, 50 - (ln-12)*2
    else:
        x_nm, y_nm, sz = 325, 85, 60 - max(0, ln-10)*2
    fn = ImageFont.truetype(title_font_path, sz)
    d.text((x_nm+1, y_nm+1), username, font=fn, fill=shadow)
    d.text((x_nm,   y_nm  ), username, font=fn, fill=white)
    
    # 11. Created & Joined At Info (Absolute position)
    info_font = ImageFont.truetype(title_font_path, size=14)

    joined_text  = f"{join_server}"
    created_text = f"{join_discord}"

    # Koordinat absolut (atur sesuka hati)
    joined_x, joined_y   = 365, 225
    created_x, created_y = 410, 250

    # Render teks dengan warna putih
    d.text((joined_x,  joined_y),  joined_text,  font=info_font, fill=white)
    d.text((created_x, created_y), created_text, font=info_font, fill=white)

    # 12. Output PNG
    out = io.BytesIO()
    bg.save(out, format="PNG")
    out.seek(0)
    return out
