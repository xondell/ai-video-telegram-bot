from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def kb(rows):
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=text, callback_data=data) for text, data in row] for row in rows]
    )


def ratio_kb(job_id: int):
    return kb([
        [("📱 Reels 9:16", f"r:{job_id}:9x16"), ("🖥 YouTube 16:9", f"r:{job_id}:16x9")],
        [("⬜ Square 1:1", f"r:{job_id}:1x1"), ("📷 Instagram 4:5", f"r:{job_id}:4x5")],
        [("🎬 Cinematic 21:9", f"r:{job_id}:21x9")],
    ])


def style_kb(job_id: int):
    return kb([
        [("🎬 Cinematic", f"s:{job_id}:cinematic"), ("🎥 Documentary", f"s:{job_id}:documentary")],
        [("📱 Modern Social", f"s:{job_id}:social"), ("🚀 Futuristic", f"s:{job_id}:futuristic")],
        [("🌿 Nature", f"s:{job_id}:nature"), ("📚 Educational", f"s:{job_id}:educational")],
        [("✨ Magical", f"s:{job_id}:magical"), ("🤖 AI / Technology", f"s:{job_id}:technology")],
    ])


def model_kb(job_id: int):
    return kb([
        [("✨ Auto — Recommended", f"m:{job_id}:auto")],
        [("⚡ PixVerse V6", f"m:{job_id}:pixverse-v6")],
        [("🎬 Hailuo 2.3 — locked", f"m:{job_id}:hailuo-2.3")],
        [("💎 Kling 3 — locked", f"m:{job_id}:kling-3")],
        [("🎥 Wan 2.7 — locked", f"m:{job_id}:wan-2.7")],
    ])


def confirm_kb(job_id: int):
    return kb([
        [("🚀 Создать", f"c:{job_id}:create")],
        [("❌ Отмена", f"c:{job_id}:cancel")],
    ])



def storyboard_kb(job_id: int):
    return kb([
        [("✅ Сценарий подходит", f"sb:{job_id}:approve")],
        [("✏️ Подправить", f"sb:{job_id}:edit"), ("🔄 Регенерировать", f"sb:{job_id}:regen")],
        [("❌ Отмена", f"sb:{job_id}:cancel")],
    ])



def scenario_source_kb(job_id: int):
    return kb([
        [("🧠 Сгенерировать ИИ", f"src:{job_id}:ai")],
        [("✍️ Свой текст", f"src:{job_id}:own")],
        [("❌ Отмена", f"src:{job_id}:cancel")],
    ])
