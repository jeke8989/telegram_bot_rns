import os
from PIL import Image, ImageDraw, ImageFont, ImageFilter

def create_circular_mask(size):
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0, size[0], size[1]), fill=255)
    return mask

def generate_og_image():
    width, height = 1200, 630
    
    # Paths
    bg_path = "assets/bg_abstract.png"
    logo_path = "assets/logo.jpg"
    out_path1 = "assets/og-proposal.png"
    out_path2 = "mini_app/static/og-proposal.png"
    
    font_bold = "app/assets/fonts/Montserrat-Bold.ttf"
    font_semi = "app/assets/fonts/Montserrat-SemiBold.ttf"
    font_regular = "app/assets/fonts/Manrope-Regular.ttf"

    # 1. Base Background
    if os.path.exists(bg_path):
        bg = Image.open(bg_path).convert("RGBA")
        # Resize/Crop to 1200x630
        w, h = bg.size
        target_ratio = width / height
        bg_ratio = w / h
        if bg_ratio > target_ratio:
            new_w = int(h * target_ratio)
            left = (w - new_w) // 2
            bg = bg.crop((left, 0, left + new_w, h))
        else:
            new_h = int(w / target_ratio)
            top = (h - new_h) // 2
            bg = bg.crop((0, top, w, top + new_h))
        bg = bg.resize((width, height), Image.Resampling.LANCZOS)
    else:
        # Fallback to dark solid color if bg generation failed
        bg = Image.new("RGBA", (width, height), "#0a0a1e")

    # Darken background slightly to ensure text readability
    dark_overlay = Image.new("RGBA", (width, height), (10, 10, 30, 140))
    bg = Image.alpha_composite(bg, dark_overlay)

    # 2. Add Logo (Circular Mask)
    if os.path.exists(logo_path):
        logo = Image.open(logo_path).convert("RGBA")
        logo_size = (100, 100)
        logo = logo.resize(logo_size, Image.Resampling.LANCZOS)
        
        # Apply circular mask
        mask = create_circular_mask(logo_size)
        logo.putalpha(mask)
        
        bg.paste(logo, (80, 80), logo)

    # 3. Add Texts
    draw = ImageDraw.Draw(bg)
    
    # Load fonts
    try:
        font_brand = ImageFont.truetype(font_bold, 50)
        font_title = ImageFont.truetype(font_bold, 64)
        font_subtitle = ImageFont.truetype(font_regular, 36)
        font_badge = ImageFont.truetype(font_semi, 24)
    except OSError:
        print("Fonts not found! Proceeding with default.")
        font_brand = ImageFont.load_default()
        font_title = ImageFont.load_default()
        font_subtitle = ImageFont.load_default()
        font_badge = ImageFont.load_default()

    # Top left: Brand Name next to logo
    draw.text((200, 100), "НейроСофт", font=font_brand, fill=(255, 255, 255, 255))
    
    # Main Title
    title = "Готовое решение для\nвашего бизнеса"
    draw.text((80, 260), title, font=font_title, fill=(255, 255, 255, 255), spacing=20)
    
    # Subtitle
    subtitle = "От идеи до запуска — разработка\nцифровых продуктов под ключ"
    draw.text((80, 430), subtitle, font=font_subtitle, fill=(167, 139, 250, 255), spacing=15) # Light purple #a78bfa

    # Bottom Right: Badge/Tag
    # Draw a rounded rectangle for a small badge
    badge_w, badge_h = 280, 50
    badge_x = width - badge_w - 80
    badge_y = height - badge_h - 60
    
    # Draw simple gradient/solid badge
    draw.rounded_rectangle((badge_x, badge_y, badge_x+badge_w, badge_y+badge_h), radius=15, fill=(120, 124, 245, 60), outline=(120, 124, 245, 120), width=2)
    draw.text((badge_x + 35, badge_y + 10), "neurosoft.pro", font=font_badge, fill=(255, 255, 255, 200))

    # Save
    bg = bg.convert("RGB") # Remove alpha for standard jpeg/png compat
    bg.save(out_path1, "PNG", quality=95)
    bg.save(out_path2, "PNG", quality=95)
    
    print(f"Generated {out_path1} and {out_path2}")

if __name__ == "__main__":
    generate_og_image()
