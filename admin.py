import os
import logging
from functools import wraps
from datetime import datetime

from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash
)
from werkzeug.exceptions import HTTPException
from sqlalchemy.orm import joinedload
from markupsafe import Markup, escape

from config import (
    FLASK_SECRET_KEY, TELEGRAM_TOKEN,
    ADMIN_USERNAME, ADMIN_PASSWORD
)
from db import SessionLocal, init_db
from models import (
    User, Category, Post, Channel, Feedback,
    DiscordChannel, DiscordAnnouncement, Filter,
    AvailableDiscordChannel
)
from telegram import Bot

# ───────────────────────────────────────────────────────
init_db()
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)
# ───────────────────────────────────────────────────────

app = Flask(
    __name__,
    template_folder=os.path.join(os.path.dirname(__file__), "templates")
)
app.secret_key = FLASK_SECRET_KEY

def nl2br(value):
    return Markup(escape(value).replace('\n', Markup('<br>\n')))
app.jinja_env.filters['nl2br'] = nl2br

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

@app.context_processor
def inject_tree():
    db = SessionLocal()
    cats = db.query(Category).all()
    db.close()
    def build_tree(nodes, parent_id=None, level=0, acc=None):
        if acc is None:
            acc = []
        for n in sorted([c for c in nodes if c.parent_id == parent_id], key=lambda x: x.name):
            acc.append((n, level))
            build_tree(nodes, parent_id=n.id, level=level+1, acc=acc)
        return acc
    return {'tree': build_tree(cats)}

# --- LOGIN / LOGOUT ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = request.form['username']
        p = request.form['password']
        if u == ADMIN_USERNAME and p == ADMIN_PASSWORD:
            session['admin_logged_in'] = True
            return redirect(url_for('dashboard'))
        flash('Неверные учетные данные', 'error')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    session.pop('admin_logged_in', None)
    return redirect(url_for('login'))

# --- DASHBOARD & STATS ---
@app.route('/')
@login_required
def dashboard():
    db = SessionLocal()
    user_count = db.query(User).count()
    stats_data = []
    for cat, lvl in inject_tree()['tree']:
        cnt = db.query(Post).filter_by(category_id=cat.id, archived=False).count()
        stats_data.append({'category': cat.name, 'count': cnt})
    # Добавим Discord-статистику:
    discord_channels = db.query(DiscordChannel).count()
    discord_filters = db.query(Filter).count()
    discord_announcements = db.query(DiscordAnnouncement).count()
    db.close()
    return render_template('dashboard.html',
                           user_count=user_count,
                           stats_data=stats_data,
                           discord_channels=discord_channels,
                           discord_filters=discord_filters,
                           discord_announcements=discord_announcements)

@app.route('/stats')
@login_required
def stats():
    db = SessionLocal()
    user_count = db.query(User).count()
    stats_data = []
    for cat, lvl in inject_tree()['tree']:
        cnt = db.query(Post).filter_by(category_id=cat.id, archived=False).count()
        stats_data.append({'category': cat.name, 'count': cnt})
    db.close()
    return render_template('stats.html', user_count=user_count, stats_data=stats_data)

# --- CATEGORIES CRUD ---
@app.route('/categories')
@login_required
def categories_view():
    return render_template('categories.html')

@app.route('/categories/add', methods=['GET', 'POST'])
@login_required
def add_category():
    db = SessionLocal()
    if request.method == 'POST':
        name = request.form['name']
        parent = request.form.get('parent_id') or None
        if parent == '0':
            parent = None
        db.add(Category(name=name, parent_id=parent))
        db.commit()
        flash('Категория добавлена', 'success')
        db.close()
        return redirect(url_for('categories_view'))
    db.close()
    return render_template('add_category.html')

@app.route('/categories/edit/<int:category_id>', methods=['GET', 'POST'])
@login_required
def edit_category(category_id):
    db = SessionLocal()
    cat = db.query(Category).get(category_id)
    if request.method == 'POST':
        cat.name = request.form['name']
        parent = request.form.get('parent_id') or None
        cat.parent_id = None if parent == '0' else parent
        db.commit()
        flash('Категория обновлена', 'success')
        db.close()
        return redirect(url_for('categories_view'))
    db.close()
    return render_template('edit_category.html', category=cat)

@app.route('/categories/delete/<int:category_id>', methods=['POST'])
@login_required
def delete_category(category_id):
    db = SessionLocal()
    db.query(Category).filter_by(id=category_id).delete()
    db.commit()
    db.close()
    flash('Категория удалена', 'success')
    return redirect(url_for('categories_view'))

# --- POSTS CRUD ---
@app.route('/posts')
@login_required
def posts_view():
    selected = request.args.get('category_id', type=int)
    db = SessionLocal()
    q = db.query(Post).options(joinedload(Post.category))
    if selected:
        q = q.filter(Post.category_id == selected)
    posts = q.all()
    db.close()
    return render_template('posts.html', posts=posts, selected_category=selected)

@app.route('/posts/add', methods=['GET', 'POST'])
@login_required
def add_post():
    db = SessionLocal()
    if request.method == 'POST':
        db.add(Post(
            title=request.form['title'],
            link=request.form['link'],
            category_id=request.form['category_id']
        ))
        db.commit()
        flash('Пост добавлен', 'success')
        db.close()
        return redirect(url_for('posts_view'))
    db.close()
    return render_template('add_post.html')

@app.route('/posts/edit/<int:post_id>', methods=['GET', 'POST'])
@login_required
def edit_post(post_id):
    db = SessionLocal()
    post = db.query(Post).get(post_id)
    if request.method == 'POST':
        post.title = request.form['title']
        post.link  = request.form['link']
        post.category_id = request.form['category_id']
        db.commit()
        flash('Пост обновлен', 'success')
        db.close()
        return redirect(url_for('posts_view'))
    db.close()
    return render_template('edit_post.html', post=post)

@app.route('/posts/archive/<int:post_id>', methods=['POST'])
@login_required
def archive_post(post_id):
    db = SessionLocal()
    p = db.query(Post).get(post_id)
    p.archived = True
    db.commit()
    db.close()
    flash('Пост перемещён в архив', 'success')
    return redirect(url_for('posts_view'))

@app.route('/posts/unarchive/<int:post_id>', methods=['POST'])
@login_required
def unarchive_post(post_id):
    db = SessionLocal()
    p = db.query(Post).get(post_id)
    p.archived = False
    db.commit()
    db.close()
    flash('Пост восстановлен', 'success')
    return redirect(url_for('posts_view'))

@app.route('/posts/delete/<int:post_id>', methods=['POST'])
@login_required
def delete_post(post_id):
    db = SessionLocal()
    db.query(Post).filter_by(id=post_id).delete()
    db.commit()
    db.close()
    flash('Пост удалён', 'success')
    return redirect(url_for('posts_view'))

# --- CHANNELS & BROADCAST ---
@app.route('/channels')
@login_required
def channels_view():
    db = SessionLocal()
    chans = db.query(Channel).all()
    db.close()
    return render_template('channels.html', channels=chans)

@app.route('/channels/add', methods=['GET', 'POST'])
@login_required
def add_channel():
    db = SessionLocal()
    if request.method == 'POST':
        db.add(Channel(
            chat_id=request.form['chat_id'],
            name=request.form['name'],
            auto_comment=request.form.get('auto_comment', '')
        ))
        db.commit()
        flash('Канал добавлен', 'success')
        db.close()
        return redirect(url_for('channels_view'))
    db.close()
    return render_template('add_channel.html')

@app.route('/channels/edit/<int:channel_id>', methods=['GET', 'POST'])
@login_required
def edit_channel(channel_id):
    db = SessionLocal()
    ch = db.query(Channel).get(channel_id)
    if request.method == 'POST':
        ch.chat_id      = request.form['chat_id']
        ch.name         = request.form['name']
        ch.auto_comment = request.form.get('auto_comment', '')
        db.commit()
        flash('Канал обновлён', 'success')
        db.close()
        return redirect(url_for('channels_view'))
    db.close()
    return render_template('edit_channel.html', channel=ch)

@app.route('/channels/delete/<int:channel_id>', methods=['POST'])
@login_required
def delete_channel(channel_id):
    db = SessionLocal()
    db.query(Channel).filter_by(id=channel_id).delete()
    db.commit()
    db.close()
    flash('Канал удалён', 'success')
    return redirect(url_for('channels_view'))

@app.route('/broadcast', methods=['GET', 'POST'])
@login_required
def broadcast():
    if request.method == 'POST':
        text = request.form['broadcast_text']
        bot = Bot(token=TELEGRAM_TOKEN)
        db = SessionLocal()
        for ch in db.query(Channel).all():
            try:
                bot.send_message(chat_id=ch.chat_id, text=text)
            except Exception as e:
                logger.error(f"Broadcast failed to {ch.chat_id}: {e}")
        db.close()
        flash('Рассылка отправлена', 'success')
        return redirect(url_for('dashboard'))
    return render_template('broadcast.html')

# --- FEEDBACK CRUD ---
@app.route('/feedbacks')
@login_required
def feedbacks_list():
    db = SessionLocal()
    feedbacks = db.query(Feedback).order_by(Feedback.created_at.desc()).all()
    db.close()
    return render_template('feedbacks.html', feedbacks=feedbacks)

@app.route('/feedbacks/<int:fb_id>')
@login_required
def feedbacks_view(fb_id):
    db = SessionLocal()
    fb = db.query(Feedback).get(fb_id)
    db.close()
    if not fb:
        flash('Заявка не найдена', 'error')
        return redirect(url_for('feedbacks_list'))
    return render_template('feedbacks_view.html', fb=fb)

@app.route('/feedbacks/edit/<int:fb_id>', methods=['GET', 'POST'])
@login_required
def feedbacks_edit(fb_id):
    db = SessionLocal()
    fb = db.query(Feedback).get(fb_id)
    if not fb:
        db.close()
        flash('Заявка не найдена', 'error')
        return redirect(url_for('feedbacks_list'))
    if request.method == 'POST':
        fb.status   = request.form['status']
        fb.progress = request.form['progress']
        db.commit()
        db.close()
        flash(f'Заявка {fb_id} обновлена', 'success')
        return redirect(url_for('feedbacks_list'))
    db.close()
    return render_template('feedbacks_edit.html', fb=fb)

@app.route('/feedbacks/delete/<int:fb_id>', methods=['POST'])
@login_required
def feedbacks_delete(fb_id):
    db = SessionLocal()
    db.query(Feedback).filter_by(id=fb_id).delete()
    db.commit()
    db.close()
    flash(f'Заявка {fb_id} удалена', 'success')
    return redirect(url_for('feedbacks_list'))

# === DISCORD CHANNELS CRUD ===
@app.route('/discord_channels')
@login_required
def discord_channels_view():
    db = SessionLocal()
    channels = db.query(DiscordChannel).all()
    users = {u.id: u for u in db.query(User).all()}
    db.close()
    return render_template('discord_channels.html', channels=channels, users=users)

@app.route('/discord_channels/add', methods=['GET', 'POST'])
@login_required
def add_discord_channel():
    db = SessionLocal()
    users = db.query(User).all()
    if request.method == 'POST':
        user_id    = request.form['user_id']
        channel_id = request.form['channel_id'].strip()
        name       = request.form.get('name', '').strip() or None
        new_ch     = DiscordChannel(user_id=user_id, channel_id=channel_id, name=name, active=True)
        db.add(new_ch)
        db.commit()
        flash('Подписка на Discord-канал добавлена.', 'success')
        db.close()
        return redirect(url_for('discord_channels_view'))
    db.close()
    return render_template('discord_channels_add.html', users=users)

@app.route('/discord_channels/edit/<int:chan_id>', methods=['GET', 'POST'])
@login_required
def edit_discord_channel(chan_id):
    db = SessionLocal()
    ch = db.query(DiscordChannel).get(chan_id)
    users = db.query(User).all()
    if not ch:
        db.close()
        flash('Канал не найден', 'error')
        return redirect(url_for('discord_channels_view'))
    if request.method == 'POST':
        ch.user_id    = request.form['user_id']
        ch.channel_id = request.form['channel_id'].strip()
        ch.name       = request.form.get('name', '').strip() or None
        ch.active     = ('active' in request.form and request.form['active'] == 'on')
        db.commit()
        flash('Discord-канал обновлён', 'success')
        db.close()
        return redirect(url_for('discord_channels_view'))
    db.close()
    return render_template('discord_channels_edit.html', channel=ch, users=users)

@app.route('/discord_channels/delete/<int:chan_id>', methods=['POST'])
@login_required
def delete_discord_channel(chan_id):
    db = SessionLocal()
    ch = db.query(DiscordChannel).get(chan_id)
    if ch:
        ch.active = False
        db.commit()
        flash('Подписка деактивирована.', 'success')
    else:
        flash('Канал не найден.', 'error')
    db.close()
    return redirect(url_for('discord_channels_view'))

# === DISCORD FILTERS CRUD ===
@app.route('/discord_filters')
@login_required
def discord_filters_view():
    db = SessionLocal()
    filters_ = db.query(Filter).all()
    users    = {u.id: u for u in db.query(User).all()}
    channels = {c.id: c for c in db.query(DiscordChannel).all()}
    db.close()
    return render_template('discord_filters.html', filters=filters_, users=users, channels=channels)

@app.route('/discord_filters/add', methods=['GET', 'POST'])
@login_required
def add_discord_filter():
    db = SessionLocal()
    users    = db.query(User).all()
    channels = db.query(DiscordChannel).filter_by(active=True).all()
    if request.method == 'POST':
        user_id    = request.form['user_id']
        channel_id = request.form['channel_id']
        keyword    = request.form['keyword'].strip()
        new_f      = Filter(user_id=user_id, channel_id=channel_id, keyword=keyword, active=True)
        db.add(new_f)
        db.commit()
        flash('Фильтр добавлен.', 'success')
        db.close()
        return redirect(url_for('discord_filters_view'))
    db.close()
    return render_template('discord_filters_add.html', users=users, channels=channels)

@app.route('/discord_filters/edit/<int:filter_id>', methods=['GET', 'POST'])
@login_required
def edit_discord_filter(filter_id):
    db = SessionLocal()
    f = db.query(Filter).get(filter_id)
    users = db.query(User).all()
    channels = db.query(DiscordChannel).filter_by(active=True).all()
    if not f:
        db.close()
        flash('Фильтр не найден', 'error')
        return redirect(url_for('discord_filters_view'))
    if request.method == 'POST':
        f.user_id    = request.form['user_id']
        f.channel_id = request.form['channel_id']
        f.keyword    = request.form['keyword'].strip()
        f.active     = ('active' in request.form and request.form['active'] == 'on')
        db.commit()
        flash('Фильтр обновлён.', 'success')
        db.close()
        return redirect(url_for('discord_filters_view'))
    db.close()
    return render_template('discord_filters_edit.html', filter=f, users=users, channels=channels)

@app.route('/discord_filters/delete/<int:filter_id>', methods=['POST'])
@login_required
def delete_discord_filter(filter_id):
    db = SessionLocal()
    f = db.query(Filter).get(filter_id)
    if f:
        f.active = False
        db.commit()
        flash('Фильтр деактивирован.', 'success')
    else:
        flash('Фильтр не найден.', 'error')
    db.close()
    return redirect(url_for('discord_filters_view'))

# === DISCORD ANNOUNCEMENTS VIEW ===
@app.route('/discord_announcements')
@login_required
def discord_announcements_view():
    db = SessionLocal()
    announcements = (
        db.query(DiscordAnnouncement)
          .order_by(DiscordAnnouncement.created_at.desc())
          .limit(50)
          .all()
    )
    channels = {c.id: c for c in db.query(DiscordChannel).all()}
    users    = {u.id: u for u in db.query(User).all()}
    db.close()
    return render_template('discord_announcements.html',
                           announcements=announcements,
                           channels=channels,
                           users=users)

@app.route('/discord_announcements/delete/<int:ann_id>', methods=['POST'])
@login_required
def delete_discord_announcement(ann_id):
    db = SessionLocal()
    db.query(DiscordAnnouncement).filter_by(id=ann_id).delete()
    db.commit()
    db.close()
    flash('Анонс удалён.', 'success')
    return redirect(url_for('discord_announcements_view'))

# === AVAILABLE DISCORD CHANNELS CRUD ===
@app.route('/available_discord_channels', methods=['GET', 'POST'])
@login_required
def available_discord_channels_view():
    """
    Список всех доступных Discord-каналов (модель AvailableDiscordChannel).
    GET  — вывод таблицы.
    POST — массовая активация выбранных записей.
    """
    db = SessionLocal()

    if request.method == 'POST':
        selected_ids = request.form.getlist('selected_ids')
        if not selected_ids:
            flash('Ни одна строка не выбрана для активации.', 'error')
            db.close()
            return redirect(url_for('available_discord_channels_view'))

        now = datetime.utcnow()
        count = 0
        for raw_id in selected_ids:
            try:
                adc_id = int(raw_id)
            except ValueError:
                continue
            ch = db.query(AvailableDiscordChannel).get(adc_id)
            if ch and not ch.is_active:
                ch.is_active = True
                ch.last_seen = now
                count += 1

        db.commit()
        flash(f'Активировано записей: {count}.', 'success')
        db.close()
        return redirect(url_for('available_discord_channels_view'))

    channels = db.query(AvailableDiscordChannel).order_by(AvailableDiscordChannel.channel_name).all()
    db.close()
    return render_template('available_discord_channels.html', channels=channels)

@app.route('/available_discord_channels/add', methods=['GET', 'POST'])
@login_required
def add_available_discord_channel():
    """
    Ручное добавление нового доступного Discord-канала.
    """
    db = SessionLocal()
    if request.method == 'POST':
        channel_id   = request.form['channel_id'].strip()
        channel_name = request.form['channel_name'].strip()

        existing = db.query(AvailableDiscordChannel).filter_by(channel_id=channel_id).first()
        if existing:
            existing.is_active = True
            existing.last_seen = datetime.utcnow()
            db.commit()
            flash('Канал уже был в списке, но помечен как активный.', 'warning')
            db.close()
            return redirect(url_for('available_discord_channels_view'))

        new_ch = AvailableDiscordChannel(
            channel_id   = channel_id,
            channel_name = channel_name,
            is_active    = True,
            last_seen    = datetime.utcnow()
        )
        db.add(new_ch)
        db.commit()
        flash('Новый Discord-канал добавлен в список доступных.', 'success')
        db.close()
        return redirect(url_for('available_discord_channels_view'))

    db.close()
    return render_template('available_discord_channels_add.html')

@app.route('/available_discord_channels/edit/<int:adc_id>', methods=['GET', 'POST'])
@login_required
def edit_available_discord_channel(adc_id):
    """
    Редактирование записи AvailableDiscordChannel: изменение имени, ID, и статуса is_active.
    """
    db = SessionLocal()
    ch = db.query(AvailableDiscordChannel).get(adc_id)
    if not ch:
        db.close()
        flash('Канал не найден', 'error')
        return redirect(url_for('available_discord_channels_view'))

    if request.method == 'POST':
        ch.channel_id   = request.form['channel_id'].strip()
        ch.channel_name = request.form['channel_name'].strip()
        ch.is_active    = ('is_active' in request.form and request.form['is_active'] == 'on')
        ch.last_seen    = datetime.utcnow()
        db.commit()
        flash('Доступный канал обновлён', 'success')
        db.close()
        return redirect(url_for('available_discord_channels_view'))

    db.close()
    return render_template('available_discord_channels_edit.html', channel=ch)

@app.route('/available_discord_channels/delete/<int:adc_id>', methods=['POST'])
@login_required
def delete_available_discord_channel(adc_id):
    """
    Деактивировать запись AvailableDiscordChannel, не удаляя её из БД.
    """
    db = SessionLocal()
    ch = db.query(AvailableDiscordChannel).get(adc_id)
    if ch:
        ch.is_active = False
        db.commit()
        flash('Канал помечен как неактивный (удален из списка).', 'success')
    else:
        flash('Канал не найден', 'error')
    db.close()
    return redirect(url_for('available_discord_channels_view'))

# --- ERROR HANDLER ---
@app.errorhandler(Exception)
def handle_exception(e):
    if isinstance(e, HTTPException):
        return e
    logger.error(f"Unhandled exception: {e}")
    return "Внутренняя ошибка", 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
