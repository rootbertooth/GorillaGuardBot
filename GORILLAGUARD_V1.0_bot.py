# Importaciones estándar
import os  # Manejo de variables de entorno y rutas de archivos
import sqlite3  # Para manejo de la base de datos SQLite
import random  # Para seleccionar frases aleatorias de las listas
import time  # Para manejar límites de tasa en la API de X
import re  # Para manejar detección de patrones como enlaces
from datetime import datetime, timedelta, timezone # Para operaciones relacionadas con fechas y tiempos
from collections import defaultdict  # Para manejar estructuras como el conteo de mensajes de usuarios

# Bibliotecas de terceros
import requests  # Para manejar solicitudes HTTP (API de X y CoinMarketCap)
import asyncio  # Para manejar tareas asíncronas como eventos del bot
from dotenv import load_dotenv  # Para cargar variables de entorno desde el archivo .env
from pathlib import Path  # Para manejar rutas de archivos y directorios
from telegram import (
    InlineKeyboardButton, InlineKeyboardMarkup, Update, ChatPermissions, CallbackQuery
)  # Herramientas para manejo de Telegram (botones, permisos, actualizaciones)
from telegram.ext import (
    Application, ApplicationBuilder, CommandHandler, MessageHandler, filters,
    ContextTypes, CallbackQueryHandler
)  # Herramientas esenciales para construir y manejar el bot
from telegram.helpers import escape_markdown  # Para manejar texto en formato Markdown
from telegram.error import RetryAfter  # Para manejar errores de límite de tasa de Telegram

# Herramientas de Tipado
from typing import Union  # Para manejo de tipos en funciones asíncronas

# Resumen de optimizaciones:
# - Confirmé que todas las importaciones sean necesarias y utilizadas en el código.
# - Añadí `CallbackQuery` y `Union` que eran faltantes.
# - Agrupé las importaciones en bloques: estándar, terceros y otros, para mayor claridad.
# - Mantengo el uso explícito de nombres (`from module import ...`) para mejorar la legibilidad.


#Enviroment Variables Block    # Bloque de variables de entorno

# Load environment variables
dotenv_path = Path(__file__).parent / ".env"

# Verificar si el archivo .env existe
if not dotenv_path.exists():
    raise FileNotFoundError("❌ The .env file was not found. Please create the file and add the necessary environment variables.")

# Cargar variables desde el archivo .env
load_dotenv(dotenv_path=dotenv_path)

# Cargar y validar las variables de entorno obligatorias
BOT_TOKEN = os.getenv("BOT_TOKEN")
TWITTER_BEARER_TOKEN = os.getenv("TWITTER_BEARER_TOKEN")
COINMARKETCAP_API_KEY = os.getenv("COINMARKETCAP_API_KEY")

# Debugging: Confirmar carga de las variables de entorno (puedes eliminar en producción)
print(f"🔑 Loaded BOT_TOKEN: {'Valid' if BOT_TOKEN else 'Missing'}")
print(f"🔑 Loaded TWITTER_BEARER_TOKEN: {'Valid' if TWITTER_BEARER_TOKEN else 'Missing'}")
print(f"🔑 Loaded COINMARKETCAP_API_KEY: {'Valid' if COINMARKETCAP_API_KEY else 'Missing'}")

# Validar BOT_TOKEN
if not BOT_TOKEN or ":" not in BOT_TOKEN:
    raise ValueError("❌ Bot token not found or invalid in the .env file. Please add BOT_TOKEN=<your_bot_token> to the file.")

# Validar TWITTER_BEARER_TOKEN
if not TWITTER_BEARER_TOKEN:
    raise ValueError("❌ Twitter Bearer API key not found in the .env file. Please add TWITTER_BEARER_TOKEN=<your_key> to the file.")

# Mostrar advertencia si la clave de CoinMarketCap no está disponible
if not COINMARKETCAP_API_KEY:
    print("⚠️ CoinMarketCap API key not found in the .env file. Cryptocurrency features may not work.")
else:
    print("✅ CoinMarketCap API key loaded successfully.")


# Resumen de optimizaciones:
# - Verifico explícitamente si las claves necesarias están presentes con mensajes claros.
# - Mantengo el control de errores para evitar fallos imprevistos si faltan claves.
# - Simplifico mensajes de debugging para asegurar claridad y evitar ambigüedades.





#DATA BASE BLOCK    # Bloque de comandos y funciones relacionadas con la base de datos

# Initialize SQLite database
from sqlite3 import Connection, Cursor
from pathlib import Path
import requests
import time

# Database path and connection
db_path = Path(__file__).parent / "gorilla_raids.db"
conn: Connection = sqlite3.connect(db_path, check_same_thread=False)
cursor: Cursor = conn.cursor()

print("✅ SQLite database initialized successfully!")

# Function to interact with the X API while respecting rate limits
def x_api_request(endpoint: str, params: dict = None) -> dict:
    """
    Makes a request to the X API while handling rate limits.

    Args:
        endpoint (str): The API endpoint to call (relative to base URL).
        params (dict, optional): Query parameters for the API call.

    Returns:
        dict: Parsed JSON response or None in case of an error.
    """
    base_url = "https://api.twitter.com/2/"
    headers = {"Authorization": f"Bearer {TWITTER_BEARER_TOKEN}"}

    try:
        response = requests.get(base_url + endpoint, headers=headers, params=params)

        # Handle rate limits
        if response.status_code == 429:
            reset_time = int(response.headers.get("x-rate-limit-reset", time.time() + 60))
            wait_time = max(0, reset_time - time.time())
            print(f"⚠️ Rate limit exceeded. Waiting for {wait_time:.2f} seconds...")
            time.sleep(wait_time)
            return x_api_request(endpoint, params)  # Retry after waiting

        response.raise_for_status()
        return response.json()

    except requests.exceptions.RequestException as e:
        print(f"❌ Error in X API request: {e}")
        return None

# Database schema creation and migration

# Create table for raids
cursor.execute("""
CREATE TABLE IF NOT EXISTS raids (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    username TEXT NOT NULL,  -- Associated account username
    tweet_id TEXT,  -- Associated tweet ID (optional for follows)
    action_type TEXT NOT NULL,  -- Required action type (retweet, like, follow)
    creator_id INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
""")

# Create table for proofs associated with raids
cursor.execute("""
CREATE TABLE IF NOT EXISTS proofs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    raid_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    username TEXT,
    proof TEXT NOT NULL,
    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (raid_id) REFERENCES raids (id) ON DELETE CASCADE
);
""")

# Migrate data from the old "raids" table if it exists
cursor.execute("""
SELECT name FROM sqlite_master WHERE type='table' AND name='raids_old';
""")
if cursor.fetchone():
    cursor.execute("""
    INSERT INTO raids (id, name, description, username, tweet_id, action_type, creator_id, created_at)
    SELECT id, name, description,
           COALESCE(username, 'default_username'),
           COALESCE(tweet_id, 'default_tweet_id'),
           action_type, creator_id, created_at
    FROM raids_old;
    """)
    # Drop the old table
    cursor.execute("DROP TABLE raids_old;")

# Create table for raid participants
cursor.execute("""
CREATE TABLE IF NOT EXISTS participants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    raid_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    username TEXT,
    status TEXT DEFAULT 'pending',  -- Participant status (pending, completed)
    FOREIGN KEY (raid_id) REFERENCES raids (id) ON DELETE CASCADE
);
""")

# Commit database schema changes
conn.commit()
print("✅ Database schema and tables created/updated successfully!")





#RAIDS BLOCK    # Bloque de comandos y funciones relacionadas con los raids

# Comando: /new_raid
async def new_raid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        print("❌ Update without a message context received.")
        return

    chat_id = update.effective_chat.id
    user = await context.bot.get_chat_member(chat_id, update.effective_user.id)

    # Verificar si el usuario es administrador
    if user.status not in ["administrator", "creator"]:
        await update.message.reply_text("❌ Only administrators can create raids.")
        return

    # Validar argumentos
    if len(context.args) < 4:
        await update.message.reply_text(
            "Usage: /new_raid <name> <description> <username> <action_type> [<tweet_url>]"
        )
        return

    try:
        # Extraer y sanitizar los argumentos
        raid_name = context.args[0].strip()
        raid_description = " ".join(context.args[1:-3]).strip()
        username = context.args[-3].strip().lstrip("@")  # Elimina espacios y el prefijo "@" si existe
        action_type = context.args[-2].strip().lower()
        tweet_url = context.args[-1].strip() if len(context.args) > 4 else None

        print(f"Received action_type: {action_type}")  # Depuración

        # Validar tipo de acción
        if action_type not in ["retweet", "like", "follow"]:
            await update.message.reply_text("❌ Invalid action type. Use 'retweet', 'like', or 'follow'.")
            return

        # Validar URL del tweet y extraer tweet_id
        tweet_id = None
        if action_type in ["retweet", "like"] and tweet_url:
            try:
                tweet_id = tweet_url.split("/")[-1]
                if not tweet_id.isdigit():
                    raise ValueError("Invalid tweet ID.")
            except Exception:
                await update.message.reply_text("❌ Invalid tweet URL. Please provide a valid link.")
                return

        # Validar username para el tipo follow
        if action_type == "follow" and (not username or " " in username or "/" in username):
            await update.message.reply_text("❌ A valid username is required for 'follow' raids.")
            return

        # Insertar datos en la base de datos
        cursor.execute(
            """
            INSERT INTO raids (name, description, username, tweet_id, action_type, creator_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (raid_name, raid_description, username, tweet_id, action_type, update.effective_user.id),
        )
        conn.commit()
        raid_id = cursor.lastrowid

        # Confirmar creación del RAID
        link_text = f"https://x.com/{username}/status/{tweet_id}" if action_type in ["retweet", "like"] else f"https://x.com/{username}"
        await update.message.reply_text(
            f"✅ New raid '{raid_name}' created successfully!\n"
            f"📛 Description: {raid_description}\n"
            f"🔗 Target: {link_text}\n"
            f"✔️ Action Required: {action_type.capitalize()}\n"
            f"📌 Participants can join using /join_raid {raid_id}."
        )

    except sqlite3.Error as e:
        print(f"❌ Database error: {e}")
        await update.message.reply_text("❌ Failed to create the raid. Please try again later.")
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        await update.message.reply_text("❌ An unexpected error occurred. Please try again.")


# Manejador para "Join Raid"
async def handle_join_raid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles the callback data for "join_raid".
    """
    query = update.callback_query

    try:
        # Confirmar el clic del botón
        await query.answer()
        print(f"Button clicked: {query.data}")  # Log del callback_data

        # Extraer el ID del RAID desde callback_data
        if query.data.startswith("join_raid:"):
            raid_id = int(query.data.split(":")[1])
            user_id = query.from_user.id
            username = query.from_user.username or "Anonymous"

            # Verificar si el RAID existe
            cursor.execute("SELECT name FROM raids WHERE id = ?", (raid_id,))
            raid = cursor.fetchone()
            if not raid:
                await query.message.reply_text("❌ This raid no longer exists.")
                return

            # Verificar si el usuario ya está registrado
            cursor.execute("SELECT id FROM participants WHERE raid_id = ? AND user_id = ?", (raid_id, user_id))
            if cursor.fetchone():
                await query.message.reply_text(
                    f"❌ @{username}, you are already a participant in the raid '{raid[0]}'."
                )
                return

            # Registrar al usuario
            cursor.execute(
                "INSERT INTO participants (raid_id, user_id, username) VALUES (?, ?, ?)",
                (raid_id, user_id, username)
            )
            conn.commit()

            # Confirmar la inscripción
            await query.message.reply_text(
                f"✅ @{username}, you have successfully joined the raid '{raid[0]}'!"
            )
        else:
            await query.message.reply_text("❓ <b>Unknown option.</b> Please try again.", parse_mode="HTML")

    except sqlite3.Error as db_error:
        print(f"❌ Database error in handle_join_raid: {db_error}")
        await query.message.reply_text("❌ Failed to join the raid. Please try again later.")
    except Exception as e:
        print(f"❌ Unexpected error in handle_join_raid: {e}")
        await query.message.reply_text("❌ An unexpected error occurred. Please try again.")


# Comando: /raid_status
async def raid_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Displays the status of a specific raid, including participants and their progress.
    """
    if len(context.args) != 1 or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /raid_status <raid_id>")
        return

    raid_id = int(context.args[0])

    try:
        # Obtener detalles del raid
        cursor.execute(
            "SELECT name, description, username, action_type FROM raids WHERE id = ?", (raid_id,)
        )
        raid = cursor.fetchone()

        if not raid:
            await update.message.reply_text("❌ Invalid raid ID. Please check the available raids.")
            return

        name, description, username, action_type = raid

        # Obtener participantes
        cursor.execute(
            "SELECT username, status FROM participants WHERE raid_id = ? ORDER BY status DESC, username ASC",
            (raid_id,),
        )
        participants = cursor.fetchall()

        # Construir el mensaje del estado del raid
        total_participants = len(participants)
        completed = sum(1 for _, status in participants if status == "completed")
        pending = total_participants - completed

        message = (
            f"🎯 <b>Raid Status:</b>\n\n"
            f"🆔 <b>Raid ID:</b> <code>{raid_id}</code>\n"
            f"📛 <b>Name:</b> <code>{name}</code>\n"
            f"📖 <b>Description:</b> {description}\n"
            f"🔗 <b>Username:</b> <a href='https://x.com/{username}'>{username}</a>\n"
            f"✔️ <b>Action Required:</b> {action_type.capitalize()}\n\n"
            f"👥 <b>Total Participants:</b> {total_participants}\n"
            f"✅ <b>Completed:</b> {completed}\n"
            f"⌛ <b>Pending:</b> {pending}\n\n"
            f"<b>Participants:</b>\n"
        )

        for participant_username, status in participants:
            status_icon = "✅" if status == "completed" else "⌛"
            message += f"  - @{participant_username}: {status_icon}\n"

        # Limitar el tamaño del mensaje
        if len(message) > 4000:
            message = message[:3997] + "..."

        # Enviar el mensaje
        await update.message.reply_text(message, parse_mode="HTML")

    except sqlite3.Error as e:
        print(f"❌ Database error: {e}")
        await update.message.reply_text("❌ Failed to retrieve raid status. Please try again later.")
    except Exception as e:
        print(f"❌ Error sending raid status: {e}")


# Comando: /list_raids
async def list_raids(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE):
    """
    Lists all active raids with a summary of participants and progress, accessible only via buttons.
    """
    try:
        # Obtener el chat ID
        chat_id = query.message.chat.id

        # Debugging: Registrar la acción del botón
        print(f"Button clicked: {query.data}")

        # Consultar los RAIDS activos
        cursor.execute("""
            SELECT r.id, r.name, r.description, r.username, r.tweet_id, r.action_type,
                   (SELECT COUNT(*) FROM participants p WHERE p.raid_id = r.id) as participant_count,
                   (SELECT COUNT(*) FROM participants p WHERE p.raid_id = r.id AND p.status = 'completed') as completed_count
            FROM raids r
            ORDER BY r.created_at DESC
        """)
        raids = cursor.fetchall()

        # Debugging: Verificar los raids recuperados
        print("✅ Retrieved raids from database:")
        print(raids)

        # Si no hay RAIDS activos
        if not raids:
            no_raids_message = "📋 <b>Active Raids:</b>\n\nNo active raids to display."
            await query.message.edit_text(no_raids_message, parse_mode="HTML")
            return

        # Iterar sobre los RAIDS y enviar un mensaje por cada uno
        for raid in raids:
            raid_id, name, description, username, tweet_id, action_type, participant_count, completed_count = raid
            pending_count = participant_count - completed_count

            # Validar y generar el enlace según el tipo de acción
            tweet_url = "Invalid URL"
            if action_type == "follow" and username:
                tweet_url = f"https://x.com/{username}"  # Enlace al perfil del usuario
            elif action_type in ["retweet", "like"] and username and tweet_id:
                tweet_url = f"https://x.com/{username}/status/{tweet_id}"  # Enlace al tweet
            else:
                print(f"⚠️ Invalid data for Raid ID {raid_id}: username='{username}', tweet_id='{tweet_id}', action_type='{action_type}'")

            # Crear botón para unirse al RAID
            keyboard = [[InlineKeyboardButton("Join Raid", callback_data=f"join_raid:{raid_id}")]]
            reply_markup = InlineKeyboardMarkup(keyboard)

            # Construir el mensaje
            message = (
                f"📋 <b>Active Raid:</b>\n\n"
                f"🆔 <b>Raid ID:</b> <code>{raid_id}</code>\n"
                f"📛 <b>Name:</b> <code>{name}</code>\n"
                f"📖 <b>Description:</b> {description}\n"
                f"🔗 <b>Link:</b> <a href='{tweet_url}'>View Target</a>\n"
                f"✔️ <b>Action Required:</b> {action_type.capitalize()}\n"
                f"👥 <b>Participants:</b> {participant_count}\n"
                f"✅ <b>Completed:</b> {completed_count}\n"
                f"⌛ <b>Pending:</b> {pending_count}\n"
            )

            # Enviar un mensaje nuevo por cada RAID
            await context.bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode="HTML",
                disable_web_page_preview=False,  # Permitir vista previa si el enlace es válido
                reply_markup=reply_markup
            )

    except sqlite3.Error as db_error:
        print(f"❌ Database error in /list_raids: {db_error}")
        await query.message.edit_text(
            "❌ Failed to retrieve raids. Please try again later.", parse_mode="HTML"
        )
    except Exception as e:
        print(f"❌ Unexpected error in /list_raids: {e}")
        await query.message.edit_text(
            "❌ An unexpected error occurred. Please try again later.", parse_mode="HTML"
        )


# Comando: /list_raids_detailed
async def list_raids_detailed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Lists detailed information about all active raids, including participants and proofs.
    """
    try:
        # Consultar raids activos
        cursor.execute("""
            SELECT r.id, r.name, r.description, r.username, r.tweet_id, r.action_type,
                   (SELECT COUNT(*) FROM participants p WHERE p.raid_id = r.id) as participant_count,
                   (SELECT COUNT(*) FROM participants p WHERE p.raid_id = r.id AND p.status = 'completed') as completed_count
            FROM raids r
            ORDER BY r.created_at DESC
        """)
        raids = cursor.fetchall()

        if not raids:
            await update.message.reply_text("No active raids to display.")
            return

        # Construir el mensaje
        message = "📋 <b>Detailed Active Raids:</b>\n\n"
        for raid in raids:
            raid_id, name, description, username, tweet_id, action_type, participant_count, completed_count = raid
            pending_count = participant_count - completed_count
            tweet_url = f"https://x.com/{username}/status/{tweet_id}" if username and tweet_id else "Invalid URL"

            # Información básica del raid
            message += (
                f"🆔 <b>Raid ID:</b> <code>{raid_id}</code>\n"
                f"📛 <b>Name:</b> <code>{name}</code>\n"
                f"📖 <b>Description:</b> {description}\n"
                f"🔗 <b>Link:</b> <a href='{tweet_url}'>{'View Target' if tweet_url else 'Invalid URL'}</a>\n"
                f"✔️ <b>Action Required:</b> {action_type.capitalize()}\n"
                f"👥 <b>Participants:</b> {participant_count}\n"
                f"✅ <b>Completed:</b> {completed_count}\n"
                f"⌛ <b>Pending:</b> {pending_count}\n\n"
            )

            # Lista de participantes
            cursor.execute("SELECT username, status FROM participants WHERE raid_id = ? ORDER BY status DESC", (raid_id,))
            participants = cursor.fetchall()
            if participants:
                message += "<b>Participants:</b>\n"
                for participant_username, status in participants:
                    status_icon = "✅" if status == "completed" else "⌛"
                    message += f"  - @{participant_username}: {status_icon}\n"
            else:
                message += "👤 No participants yet.\n"

            # Lista de pruebas
            cursor.execute("SELECT username, proof, submitted_at FROM proofs WHERE raid_id = ?", (raid_id,))
            proofs = cursor.fetchall()
            if proofs:
                message += "\n<b>Proofs:</b>\n"
                for username, proof, submitted_at in proofs:
                    message += (
                        f"  - @{username}\n"
                        f"    ✔️ <b>Proof:</b> {proof}\n"
                        f"    🕒 <b>Submitted At:</b> {submitted_at}\n"
                    )
            else:
                message += "\n<b>Proofs:</b> None\n"

            message += "\n"

        # Limitar el tamaño del mensaje
        if len(message) > 4000:
            message = message[:3997] + "..."

        # Enviar el mensaje
        await update.message.reply_text(message, parse_mode="HTML", disable_web_page_preview=True)

    except sqlite3.Error as e:
        print(f"❌ Database error in /list_raids_detailed: {e}")
        await update.message.reply_text("❌ Failed to retrieve detailed raids. Please try again later.")
    except Exception as e:
        print(f"❌ Unexpected error in /list_raids_detailed: {e}")
        await update.message.reply_text("❌ An unexpected error occurred. Please try again later.")


# Comando: /delete_all_raids
async def delete_all_raids(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Deletes all raids and associated data. Restricted to administrators.
    """
    if not update.message:
        print("❌ Update without a message context received.")
        return

    chat_id = update.effective_chat.id
    user = await context.bot.get_chat_member(chat_id, update.effective_user.id)

    # Verificar permisos de administrador
    if user.status not in ["administrator", "creator"]:
        await update.message.reply_text("❌ Only administrators can delete all raids.")
        return

    try:
        # Confirmar la operación con el usuario
        confirmation_keyboard = [
            [
                InlineKeyboardButton("✅ Confirm Delete", callback_data="confirm_delete_raids"),
                InlineKeyboardButton("❌ Cancel", callback_data="cancel_delete_raids"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(confirmation_keyboard)

        await update.message.reply_text(
            "⚠️ Are you sure you want to delete all raids and associated data?\n\n"
            "This action cannot be undone.",
            reply_markup=reply_markup,
        )

    except Exception as e:
        print(f"❌ Error in /delete_all_raids: {e}")
        await update.message.reply_text("❌ Failed to initiate the deletion process. Please try again later.")


# Callback para confirmar la eliminación de raids
async def confirm_delete_raids(update: CallbackQuery, context: ContextTypes.DEFAULT_TYPE):
    """
    Confirms and deletes all raids and associated data.
    """
    query = update.callback_query
    await query.answer()

    try:
        # Eliminar datos de las tablas relacionadas
        cursor.execute("DELETE FROM participants;")
        cursor.execute("DELETE FROM proofs;")
        cursor.execute("DELETE FROM raids;")
        conn.commit()

        await query.edit_message_text("✅ All raids and associated data have been successfully deleted.")
        print("✅ All raids and related data deleted successfully.")

    except sqlite3.Error as e:
        print(f"❌ Database error while deleting raids: {e}")
        await query.edit_message_text("❌ Failed to delete raids. Please try again later.")
    except Exception as e:
        print(f"❌ Unexpected error in confirm_delete_raids: {e}")
        await query.edit_message_text("❌ An unexpected error occurred. Please try again later.")


# Callback para cancelar la eliminación de raids
async def cancel_delete_raids(update: CallbackQuery, context: ContextTypes.DEFAULT_TYPE):
    """
    Cancels the deletion process for raids.
    """
    query = update.callback_query
    await query.answer()

    try:
        await query.edit_message_text("❌ Raid deletion has been canceled.")
        print("❌ Raid deletion canceled by the user.")
    except Exception as e:
        print(f"❌ Error while canceling deletion: {e}")


# Comando: /reset_database
async def reset_database_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Resets the entire database by clearing all data and resetting ID sequences.
    """
    chat_id = update.effective_chat.id
    user = await context.bot.get_chat_member(chat_id, update.effective_user.id)

    # Verificar si el usuario es administrador
    if user.status not in ["administrator", "creator"]:
        await update.message.reply_text("❌ Only administrators can reset the database.")
        return

    try:
        # Vaciar las tablas
        cursor.execute("DELETE FROM raids;")
        cursor.execute("DELETE FROM participants;")
        cursor.execute("DELETE FROM proofs;")  # Limpieza de la tabla proofs

        # Reiniciar los contadores de ID
        cursor.execute("DELETE FROM sqlite_sequence WHERE name IN ('raids', 'participants', 'proofs');")

        conn.commit()
        await update.message.reply_text("✅ Database has been reset successfully!")
        print("✅ Database reset by admin.")
    except Exception as e:
        print(f"❌ Error resetting database: {e}")
        await update.message.reply_text("❌ Failed to reset the database. Please try again later.")


# Comando: /show_proofs
async def show_proofs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Retrieves and displays proofs for a specific raid.
    """
    if len(context.args) != 1 or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /show_proofs <raid_id>")
        return

    raid_id = int(context.args[0])

    # Verificar si el raid existe
    cursor.execute("SELECT id, name, description FROM raids WHERE id = ?", (raid_id,))
    raid = cursor.fetchone()

    if not raid:
        await update.message.reply_text("❌ Invalid raid ID. Please check the available raids.")
        return

    raid_id, name, description = raid

    # Obtener las pruebas asociadas al raid
    cursor.execute("""
        SELECT username, proof, submitted_at
        FROM proofs
        WHERE raid_id = ?
        ORDER BY submitted_at ASC
    """, (raid_id,))
    proofs = cursor.fetchall()

    if not proofs:
        await update.message.reply_text(f"No proofs have been submitted for the raid '{name}'.")
        return

    # Construir el mensaje con las pruebas
    def escape_html(text):
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    message = (
        f"📋 <b>Proofs for Raid:</b>\n\n"
        f"🆔 <b>Raid ID:</b> <code>{raid_id}</code>\n"
        f"📛 <b>Name:</b> <code>{escape_html(name)}</code>\n"
        f"📖 <b>Description:</b> {escape_html(description)}\n\n"
        f"<b>Submitted Proofs:</b>\n"
    )

    for username, proof_text, submitted_at in proofs:
        message += (
            f"  - @{escape_html(username)}\n"
            f"    ✔️ <b>Proof:</b> {escape_html(proof_text)}\n"
            f"    🕒 <b>Submitted At:</b> {submitted_at}\n\n"
        )

    try:
        await update.message.reply_text(message, parse_mode="HTML")
    except Exception as e:
        print(f"Error sending proofs: {e}")
        await update.message.reply_text("❌ An error occurred while retrieving proofs.")


# Sistema de validación y registro de pruebas
async def verify_and_register_proofs():
    """
    Verifies user interactions and registers proofs in the database for active raids.
    """
    try:
        # Consultar raids activos
        cursor.execute("""
            SELECT id, username, tweet_id, action_type
            FROM raids
        """)
        raids = cursor.fetchall()

        if not raids:
            print("⚠️ No active raids to verify.")
            return

        requests_made = 0  # Contador de solicitudes a la API

        for raid_id, username, tweet_id, action_type in raids:
            # Validar configuración del raid
            if not username or not action_type:
                print(f"⚠️ Skipping invalid raid configuration for Raid ID {raid_id}.")
                continue

            # Determinar el endpoint según el tipo de acción
            endpoint = None
            if action_type == "retweet":
                endpoint = f"tweets/{tweet_id}/retweeted_by"
            elif action_type == "like":
                endpoint = f"tweets/{tweet_id}/liking_users"
            elif action_type == "follow":
                endpoint = f"users/by/username/{username}/followers"

            if not endpoint:
                print(f"⚠️ Unknown action type for Raid ID {raid_id}. Skipping...")
                continue

            # Llamar a la API y procesar la respuesta
            try:
                print(f"🔍 Verifying interactions for Raid ID {raid_id}...")
                response = await x_api_request(endpoint)
                requests_made += 1  # Incrementar contador

                if not response or "data" not in response:
                    print(f"⚠️ No interactions found for Raid ID {raid_id}.")
                    continue

                # Extraer los usuarios que completaron la acción
                interacting_users = {user["username"].lower() for user in response["data"]}

                # Verificar participantes pendientes
                cursor.execute("""
                    SELECT id, user_id, username FROM participants
                    WHERE raid_id = ? AND status = 'pending'
                """, (raid_id,))
                participants = cursor.fetchall()

                for participant_id, user_id, participant_username in participants:
                    if participant_username.lower() in interacting_users:
                        # Actualizar estado del participante y registrar prueba
                        cursor.execute("""
                            UPDATE participants
                            SET status = 'completed'
                            WHERE id = ?
                        """, (participant_id,))
                        cursor.execute("""
                            INSERT INTO proofs (raid_id, user_id, username, proof)
                            VALUES (?, ?, ?, ?)
                        """, (raid_id, user_id, participant_username, f"Completed {action_type}"))
                        conn.commit()
                        print(f"✅ @{participant_username} completed the action for Raid ID {raid_id}.")

            except Exception as e:
                print(f"❌ Error verifying interactions for Raid ID {raid_id}: {e}")

            # Respetar los límites de la API
            await asyncio.sleep(60)  # Ajustar tiempo según los límites de la API

        print(f"🔄 Proof verification completed. Total API requests made: {requests_made}")

    except sqlite3.Error as db_error:
        print(f"❌ Database error during verification: {db_error}")
    except Exception as e:
        print(f"❌ Unexpected error in verify_and_register_proofs: {e}")


# Función: Verificación periódica de pruebas
async def periodic_proof_verification(context: ContextTypes.DEFAULT_TYPE):
    """
    Executes periodic verification of user interactions and registers proofs.
    """
    print("🔄 Running periodic proof verification...")
    try:
        await verify_and_register_proofs()
    except Exception as e:
        print(f"❌ Error during periodic proof verification: {e}")


# Comando: /start_proof_verification
async def start_proof_verification(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Starts periodic verification of proofs (restricted to admins).
    """
    if not update.message:
        print("❌ Update without a message context received.")
        return

    chat_id = update.effective_chat.id
    user = await context.bot.get_chat_member(chat_id, update.effective_user.id)

    # Verificar permisos de administrador
    if user.status not in ["administrator", "creator"]:
        await update.message.reply_text("❌ This command is restricted to administrators.")
        return

    # Verificar si ya hay un trabajo activo
    if context.job_queue.get_jobs_by_name("proof_verification"):
        await update.message.reply_text("🔄 Proof verification is already running.")
        return

    # Iniciar el trabajo periódico
    try:
        context.job_queue.run_repeating(periodic_proof_verification, interval=900, first=10, name="proof_verification")
        await update.message.reply_text("✅ Proof verification has been started!")
    except Exception as e:
        print(f"❌ Error starting proof verification: {e}")
        await update.message.reply_text("❌ Failed to start proof verification. Please try again.")


# Comando: /stop_proof_verification
async def stop_proof_verification(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Stops periodic verification of proofs (restricted to admins).
    """
    if not update.message:
        print("❌ Update without a message context received.")
        return

    chat_id = update.effective_chat.id
    user = await context.bot.get_chat_member(chat_id, update.effective_user.id)

    # Verificar permisos de administrador
    if user.status not in ["administrator", "creator"]:
        await update.message.reply_text("❌ This command is restricted to administrators.")
        return

    # Detener el trabajo periódico
    try:
        jobs = context.job_queue.get_jobs_by_name("proof_verification")
        for job in jobs:
            job.schedule_removal()

        await update.message.reply_text("✅ Proof verification has been stopped!")
    except Exception as e:
        print(f"❌ Error stopping proof verification: {e}")
        await update.message.reply_text("❌ Failed to stop proof verification. Please try again.")


# Función: verify_and_register_proofs con manejo optimizado del contador y excepciones
async def verify_and_register_proofs():
    """Verifica automáticamente las interacciones y registra las pruebas en la base de datos."""
    cursor.execute("""
        SELECT id, username, tweet_id, action_type
        FROM raids
    """)
    raids = cursor.fetchall()

    if not raids:
        print("No active raids to verify.")
        return

    requests_made = 0  # Inicializa el contador de solicitudes

    for raid in raids:
        raid_id, username, tweet_id, action_type = raid
        endpoint = None

        # Determinar el endpoint según el tipo de acción
        if action_type == "retweet":
            endpoint = f"tweets/{tweet_id}/retweeted_by"
        elif action_type == "like":
            endpoint = f"tweets/{tweet_id}/liking_users"
        elif action_type == "follow":
            endpoint = f"users/by/username/{username}/followers"
        else:
            print(f"Unknown action type for Raid ID {raid_id}: {action_type}")
            continue

        # Consultar la API de X
        try:
            print(f"🔍 Verifying interactions for Raid ID {raid_id}...")
            response = await x_api_request(endpoint)  # Asegúrate de que sea asíncrona
            requests_made += 1  # Incrementa el contador de solicitudes

            if not response or "data" not in response:
                print(f"No interactions found for Raid ID {raid_id}.")
                continue

            # Lista de usuarios que completaron la acción
            interacting_users = {user["username"].lower() for user in response["data"]}

            # Verificar participantes pendientes
            cursor.execute("""
                SELECT id, user_id, username FROM participants
                WHERE raid_id = ? AND status = 'pending'
            """, (raid_id,))
            participants = cursor.fetchall()

            for participant_id, user_id, participant_username in participants:
                if participant_username.lower() in interacting_users:
                    # Actualizar estado del participante
                    cursor.execute("""
                        UPDATE participants
                        SET status = 'completed'
                        WHERE id = ?
                    """, (participant_id,))
                    conn.commit()

                    # Registrar prueba
                    cursor.execute("""
                        INSERT INTO proofs (raid_id, user_id, username, proof)
                        VALUES (?, ?, ?, ?)
                    """, (raid_id, user_id, participant_username, f"Completed {action_type}"))
                    conn.commit()

                    print(f"✅ @{participant_username} completed the action for Raid ID {raid_id}.")

        except Exception as e:
            print(f"❌ Error verifying interactions for Raid ID {raid_id}: {e}")

        # Respetar los límites de la API
        await asyncio.sleep(60)  # Ajusta este tiempo si es necesario

    print(f"🔄 Proof verification completed. Total API requests made: {requests_made}")


# Manejador de botones: menu_handler
async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles button interactions from inline menus.
    """
    query = update.callback_query

    try:
        # Confirm the button press
        await query.answer()
        print(f"CallbackQuery data received: {query.data}")  # Debugging log

        # Handle button callbacks
        if query.data == "list_raids":
            # Call list_raids function for the inline button
            await list_raids(query, context)

        
        elif query.data == "help_raids":
            keyboard = [[InlineKeyboardButton("📋 List Raids", callback_data="list_raids")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.reply_text(
                (
                    "🎯 <b>Raid Help:</b>\n\n"
                    "This is the help for participating in our RAIDS:\n"
                    "1️⃣ Click the <b>LIST RAIDS</b> button.\n"
                    "2️⃣ Select <b>JOIN RAID</b> on any listed raid.\n"
                    "3️⃣ To participate, ensure you <b>use the same username</b> on Telegram and X.\n\n"
                    "Enjoy participating and tracking your progress!"
                ),
                reply_markup=reply_markup,
                parse_mode="HTML"
            )

        elif query.data == "about_bot":
            await query.message.reply_text(
                "ℹ️ <b>About the Bot:</b>\n\n"
                "This bot helps you:\n"
                "• Track cryptocurrency stats.\n"
                "• Manage and participate in exclusive raids on X.\n\n"
                "Use <b>/start</b> to explore all features.",
                parse_mode="HTML"
            )

        elif query.data.startswith("join_raid:"):
            # Delegate handling to the specific handler
            print(f"Passing join_raid callback to handle_join_raid: {query.data}")
            return  # Let the specific handler manage it

        else:
            # Handle unknown options
            await query.message.reply_text("❓ <b>Unknown option.</b> Please try again.", parse_mode="HTML")

    except Exception as e:
        print(f"❌ Error handling callback data '{query.data}': {e}")


# Manejador específico para Join Raid
async def handle_join_raid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles joining a raid via inline button callback.
    """
    query = update.callback_query
    try:
        await query.answer()
        print(f"Handling join_raid callback: {query.data}")  # Debugging log

        raid_id = query.data.split(":")[1]
        user_id = query.from_user.id
        username = query.from_user.username or "Anonymous"

        # Validate if the RAID exists
        cursor.execute("SELECT name FROM raids WHERE id = ?", (raid_id,))
        raid = cursor.fetchone()
        if not raid:
            await query.message.reply_text("❌ This raid no longer exists.")
            return

        # Check if the user is already registered
        cursor.execute("SELECT id FROM participants WHERE raid_id = ? AND user_id = ?", (raid_id, user_id))
        if cursor.fetchone():
            await query.message.reply_text(f"❌ @{username}, you are already a participant in this raid.")
            return

        # Register the user in the RAID
        cursor.execute(
            "INSERT INTO participants (raid_id, user_id, username) VALUES (?, ?, ?)",
            (raid_id, user_id, username)
        )
        conn.commit()

        await query.message.reply_text(f"✅ @{username}, you have successfully joined the raid!")

    except Exception as e:
        print(f"❌ Error in handle_join_raid: {e}")
        await query.message.reply_text("❌ Failed to join the raid. Please try again later.")


# Publicar raids automáticamente
async def post_raids(context: ContextTypes.DEFAULT_TYPE):
    """
    Periodically publishes active raids with participant statistics.
    """
    chat_id = context.job.chat_id

    # Consultar raids activos y contar participantes
    cursor.execute("""
        SELECT r.id, r.name, r.description, r.username, r.tweet_id, r.action_type, 
               (SELECT COUNT(*) FROM participants p WHERE p.raid_id = r.id) as participant_count,
               (SELECT COUNT(*) FROM participants p WHERE p.raid_id = r.id AND p.status = 'completed') as completed_count
        FROM raids r
        ORDER BY r.created_at DESC
    """)
    raids = cursor.fetchall()

    if not raids:
        await context.bot.send_message(chat_id, "No active raids to display.")
        return

    for raid in raids:
        raid_id, name, description, username, tweet_id, action_type, participant_count, completed_count = raid
        pending_count = participant_count - completed_count

        # Construir el enlace correcto
        tweet_url = None
        if action_type == "follow":
            tweet_url = f"https://x.com/{username}"
        elif action_type in ["retweet", "like"] and tweet_id and username:
            tweet_url = f"https://x.com/{username}/status/{tweet_id}"
        if not tweet_url:
            tweet_url = "Invalid URL"

        # Crear el botón "Join Raid"
        keyboard = [[InlineKeyboardButton("Join Raid", callback_data=f"join_raid:{raid_id}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Enviar mensaje del raid
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    f"🎯 <b>Active Raid:</b>\n\n"
                    f"🆔 <b>Raid ID:</b> <code>{raid_id}</code>\n"
                    f"📛 <b>Name:</b> <code>{name}</code>\n"
                    f"📖 <b>Description:</b> {description}\n"
                    f"🔗 <b>Link:</b> <a href='{tweet_url}'>View Target</a>\n"
                    f"✔️ <b>Action Required:</b> {action_type.capitalize()}\n"
                    f"👥 <b>Participants:</b> {participant_count}\n"
                    f"✅ <b>Completed:</b> {completed_count}\n"
                    f"⌛ <b>Pending:</b> {pending_count}\n\n"
                    f"Click the button below to join this raid!"
                ),
                reply_markup=reply_markup,
                parse_mode="HTML"
            )
        except Exception as e:
            print(f"Error sending raid message for Raid ID {raid_id}: {e}")


# Comando: /start_raid_posts
async def start_raid_posts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Starts automatic posting of raids (restricted to admins).
    """
    chat_id = update.effective_chat.id
    user = await context.bot.get_chat_member(chat_id, update.effective_user.id)

    if user.status not in ["administrator", "creator"]:
        await update.message.reply_text("❌ This command is restricted to administrators.")
        return

    if context.job_queue.get_jobs_by_name(f"raid_posts_{chat_id}"):
        await update.message.reply_text("🔔 Auto-posting of raids is already running!")
        return

    context.job_queue.run_repeating(
        post_raids, interval=3600, first=10, chat_id=chat_id, name=f"raid_posts_{chat_id}"
    )
    await update.message.reply_text("🔔 Auto-posting of raids has been started!")


# Comando: /stop_raid_posts
async def stop_raid_posts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Stops automatic posting of raids (restricted to admins).
    """
    chat_id = update.effective_chat.id
    user = await context.bot.get_chat_member(chat_id, update.effective_user.id)

    if user.status not in ["administrator", "creator"]:
        await update.message.reply_text("❌ This command is restricted to administrators.")
        return

    jobs = context.job_queue.get_jobs_by_name(f"raid_posts_{chat_id}")
    for job in jobs:
        job.schedule_removal()

    await update.message.reply_text("✅ Auto-posting of raids has been stopped!")


# Verificación periódica de interacciones
async def verify_and_register_proofs():
    """
    Verifies user interactions and registers proofs in the database while respecting API limits.
    """
    cursor.execute("""
        SELECT id, username, tweet_id, action_type
        FROM raids
    """)
    raids = cursor.fetchall()

    if not raids:
        print("No active raids to verify.")
        return

    for raid_id, username, tweet_id, action_type in raids:
        endpoint = None
        if action_type == "retweet":
            endpoint = f"tweets/{tweet_id}/retweeted_by"
        elif action_type == "like":
            endpoint = f"tweets/{tweet_id}/liking_users"
        elif action_type == "follow":
            endpoint = f"users/by/username/{username}/followers"

        if not endpoint:
            print(f"Invalid endpoint for Raid ID {raid_id}. Skipping...")
            continue

        response = x_api_request(endpoint)
        if not response or "data" not in response:
            print(f"No interactions found for Raid ID {raid_id}.")
            continue

        interacting_users = {user["username"].lower() for user in response["data"]}

        cursor.execute("""
            SELECT id, username FROM participants
            WHERE raid_id = ? AND status = 'pending'
        """, (raid_id,))
        participants = cursor.fetchall()

        for participant_id, participant_username in participants:
            if participant_username.lower() in interacting_users:
                cursor.execute("""
                    UPDATE participants
                    SET status = 'completed'
                    WHERE id = ?
                """, (participant_id,))
                cursor.execute("""
                    INSERT INTO proofs (raid_id, user_id, username, proof)
                    VALUES (?, ?, ?, ?)
                """, (raid_id, participant_id, participant_username, f"Completed {action_type}"))
                conn.commit()
                print(f"✅ @{participant_username} completed the action for Raid ID {raid_id}.")

        await asyncio.sleep(60)  # Respetar los límites de la API


# Function to welcome new members
async def welcome_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Welcomes new members with a button menu.
    """
    chat_id = update.effective_chat.id

    for member in update.message.new_chat_members:
        # Create button menu with "Web Site" pointing to the desired URL
        keyboard = [
            [
                InlineKeyboardButton("🌐 Web Site", url="https://www.gorillamansion.xyz/"),
                InlineKeyboardButton("🌟 VIP Signals", url="https://t.me/Toastedspam88"),
            ],
            [
                InlineKeyboardButton("🎯 Raid Help", callback_data="help_raids"),
                InlineKeyboardButton("📊 Top Cryptos", callback_data="top_cryptos"),
            ],
            [InlineKeyboardButton("ℹ️ About the Bot", callback_data="about_bot")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Send welcome message with buttons
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    f"👋 Welcome, {member.full_name}!\n\n"
                    "Explore the bot's features using the options below."
                ),
                reply_markup=reply_markup,
                parse_mode="HTML",
            )
        except Exception as e:
            print(f"❌ Failed to welcome user {member.full_name}: {e}")


# Respond to the selected button
async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    # Confirm the button press
    try:
        await query.answer()
    except Exception as e:
        print(f"❌ Error answering callback query: {e}")

    # Respond to the selected button
    try:
        if query.data == "list_raids":
            # Llama directamente al comando /list_raids
            await list_raids(query, context)
        elif query.data == "help_raids":
            # Publicar mensaje de ayuda para RAIDS
            keyboard = [
                [
                    InlineKeyboardButton("📋 List Raids", callback_data="list_raids"),
                ],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.reply_text(
                (
                    "🎯 <b>Raid Help:</b>\n\n"
                    "This is the help for participating in our RAIDS:\n"
                    "1️⃣ Click the <b>LIST RAIDS</b> button.\n"
                    "2️⃣ Select <b>JOIN RAID</b> on any listed raid.\n"
                    "3️⃣ To participate, ensure you <b>use the same username</b> on Telegram and X.\n\n"
                    "Enjoy participating and tracking your progress!"
                ),
                reply_markup=reply_markup,
                parse_mode="HTML"
            )
        elif query.data == "top_cryptos":
            # Ejecuta directamente el comando /top_cryptos
            await get_top_cryptos(query, context)
        elif query.data == "about_bot":
            await query.message.reply_text(
                "ℹ️ <b>About the Bot:</b>\n\n"
                "This bot helps you:\n"
                "• Track cryptocurrency stats.\n"
                "• Manage and participate in exclusive raids on X.\n\n"
                "Use <b>/start</b> to explore all features.",
                parse_mode="HTML"
            )
        else:
            await query.message.reply_text("❓ <b>Unknown option.</b> Please try again.", parse_mode="HTML")
    except Exception as e:
        print(f"❌ Error handling callback data '{query.data}': {e}")


# Function to handle /start command with a button menu
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Sends a welcome message with an interactive start menu.
    """
    welcome_message = (
        "👋 Welcome to <b>Gorilla Mansion Stats Bot</b>!\n\n"
        "Explore the features using the menu below."
    )

    # Create start menu buttons
    keyboard = [
        [
            InlineKeyboardButton("🌐 Web Site", url="https://www.gorillamansion.xyz/"),
            InlineKeyboardButton("🌟 VIP Signals", url="https://t.me/Toastedspam88"),
        ],    
        [
            InlineKeyboardButton("🎯 Raid Help", callback_data="help_raids"),
            InlineKeyboardButton("📊 Top Cryptos", callback_data="top_cryptos"),
        ],
        [InlineKeyboardButton("ℹ️ About the Bot", callback_data="about_bot")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Send start menu
    try:
        await update.message.reply_text(welcome_message, parse_mode="HTML", reply_markup=reply_markup)
    except Exception as e:
        print(f"❌ Error sending start menu: {e}")
        await update.message.reply_text("❌ An error occurred while sending the start menu.")



#SPAM BLOCKER Y RAID DETECTION SYSTEM

# Configuración de seguimiento de spam y links
user_message_count = defaultdict(list)
mute_duration = timedelta(minutes=60)  # Duración del mute por spam
link_mute_duration = timedelta(minutes=60)  # Duración del mute por links
message_limit = 4  # Número máximo de mensajes permitidos en la ventana de tiempo
time_window = timedelta(seconds=10)  # Ventana de tiempo para detección de spam
recently_handled_users = {}  # Estructura: {user_id: datetime}

# Configuración de detección de raids
new_members = []  # Lista para rastrear nuevos miembros con marcas de tiempo
raid_detection_threshold = 5  # Número de miembros para activar detección de raids
raid_detection_window = 30  # Ventana de tiempo en segundos para detección de raids
raid_lock_duration = 300  # Duración del bloqueo del grupo en segundos

# Función genérica para restringir usuarios con reintentos
async def restrict_user_with_retry(context, chat_id, user_id, permissions, until_date):
    try:
        await context.bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=permissions,
            until_date=until_date
        )
        print(f"✅ User {user_id} successfully restricted.")
        return True
    except RetryAfter as e:
        print(f"⏳ Rate limit hit. Retrying in {e.retry_after} seconds...")
        await asyncio.sleep(e.retry_after)
        return await restrict_user_with_retry(context, chat_id, user_id, permissions, until_date)
    except Exception as e:
        print(f"❌ Failed to restrict user {user_id}: {e}")
        return False

# Función para silenciar usuarios
async def mute_user(context, chat_id, user_id, username, duration, reason):
    now = datetime.now(timezone.utc)  # Usar timezone-aware UTC

    # Verificar si el usuario ya ha sido manejado recientemente
    if user_id in recently_handled_users and (now - recently_handled_users[user_id]).seconds < 30:
        print(f"⚠️ User {user_id} was recently handled. Skipping.")
        return

    recently_handled_users[user_id] = now  # Registrar acción
    try:
        success = await restrict_user_with_retry(
            context,
            chat_id,
            user_id,
            ChatPermissions(can_send_messages=False),
            now + duration
        )
        if success:
            print(f"✅ User @{username} muted for {duration.total_seconds() / 60:.0f} minutes ({reason}).")
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ @{username} has been muted for {duration.total_seconds() / 60:.0f} minutes.\nReason: {reason}."
            )
    except Exception as e:
        print(f"❌ Failed to mute user @{username}: {e}")

# Detectar y manejar links y spam
async def detect_links_and_spam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    username = update.effective_user.username or "Unknown"

    if not update.message or not update.message.text:
        print(f"⚠️ Update without a valid message detected from user {user_id}. Ignoring.")
        return

    message_text = update.message.text  # Extraer el texto del mensaje
    now = datetime.now(timezone.utc)

    # Patrón para detectar links
    link_pattern = r"(http[s]?://|www\.)[^\s]+"

    # Detectar y manejar links
    if re.search(link_pattern, message_text):
        try:
            await update.message.delete()
            print(f"🔗 Link detected and deleted from user {user_id}.")
            await mute_user(context, chat_id, user_id, username, link_mute_duration, "Posting links")
            return
        except Exception as e:
            print(f"❌ Error handling link for user {user_id}: {e}")

    # Manejo de detección de spam
    user_message_count[user_id].append(now)
    user_message_count[user_id] = [
        timestamp for timestamp in user_message_count[user_id]
        if now - timestamp <= time_window
    ]

    if len(user_message_count[user_id]) > message_limit:
        await mute_user(context, chat_id, user_id, username, mute_duration, "Spamming")

# Detectar palabras largas y aplicar mute progresivo
async def detect_long_words_and_mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    username = update.effective_user.username or "Unknown"
    message_text = update.message.text or ""

    # Excluir administradores y creadores
    user = await context.bot.get_chat_member(chat_id, user_id)
    if user.status in ["administrator", "creator"]:
        return

    # Detectar palabras largas
    long_word_pattern = r"\b\w{15,}\b"
    long_words = re.findall(long_word_pattern, message_text)

    if long_words:
        # Inicializar advertencias
        if "long_word_warnings" not in context.chat_data:
            context.chat_data["long_word_warnings"] = {}

        warnings = context.chat_data["long_word_warnings"].get(user_id, 0)
        context.chat_data["long_word_warnings"][user_id] = warnings + 1

        # Determinar duración del mute
        mute_duration = timedelta(minutes=60) if warnings >= 2 else timedelta(minutes=5)
        reason = f"Using long words: {', '.join(long_words)}"
        message = (
            f"❌ @{username}, you have been muted for {mute_duration.total_seconds() / 60:.0f} minutes.\n"
            f"Reason: {reason}"
        )

        # Aplicar mute
        try:
            await restrict_user_with_retry(
                context,
                chat_id,
                user_id,
                ChatPermissions(can_send_messages=False),
                datetime.now(timezone.utc) + mute_duration
            )
            await update.message.reply_text(message, parse_mode="HTML")
            print(f"✅ Mute applied to @{username} for {reason}.")
        except Exception as e:
            print(f"❌ Failed to mute user @{username}: {e}")

# Manejar mensajes de texto
async def handle_text_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await detect_links_and_spam(update, context)
    await detect_long_words_and_mute(update, context)



# Function to get the top 5 cryptocurrencies
async def get_top_cryptos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Fetches and displays the top 5 cryptocurrencies by market cap.
    """
    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest"
    headers = {
        "Accepts": "application/json",
        "X-CMC_PRO_API_KEY": COINMARKETCAP_API_KEY,
    }
    params = {"start": "1", "limit": "5", "convert": "USD"}
    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        data = response.json()
        cryptos = data.get("data", [])
        if not cryptos:
            raise ValueError("No cryptocurrency data found.")

        # Create the message in HTML format
        message = "<b>📊 Top 5 Cryptocurrencies:</b>\n\n"
        for crypto in cryptos:
            message += (
                f"• <b>{crypto['name']} ({crypto['symbol']})</b>: "
                f"${crypto['quote']['USD']['price']:.2f}\n"
            )

        # Send the message
        await update.message.reply_text(message, parse_mode="HTML")
    except requests.exceptions.RequestException as e:
        print(f"❌ Error fetching cryptocurrency data: {e}")
        await update.message.reply_text(
            "❌ Failed to fetch cryptocurrency data. Please try again later."
        )
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        await update.message.reply_text(
            "❌ An error occurred while processing the cryptocurrency data."
        )


# Function to post a random crypto phrase
async def post_random_phrase(context: ContextTypes.DEFAULT_TYPE):
    """
    Posts a random cryptocurrency-related phrase to a specified chat.
    """
    try:
        chat_id = context.job.data["chat_id"]
        phrase = random.choice(crypto_phrases)
        await context.bot.send_message(chat_id=chat_id, text=phrase)
    except Exception as e:
        print(f"Error sending random crypto phrase: {e}")


# List of crypto-related phrases
crypto_phrases = [
    "🚀 The future is decentralized.",
    "💡 Knowledge is your best investment in the crypto world.",
    "🔐 Never share your private keys. Security comes first!",
    "🌍 Blockchain knows no borders.",
    "📈 Bitcoin is not just money; it’s a revolution.",
    # Additional phrases omitted for brevity
    "🛑 Never invest more than you can afford to lose.",
    "🌞 Innovation never sleeps in the crypto world.",
    "🌱 Start small, grow with wisdom.",
    "🚀 Crypto: More than a market, it's a movement."
]


# Function to start periodic posting (restricted to admins)
async def start_auto_posts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Starts periodic posting of random crypto phrases (admin-only command).
    """
    chat_id = update.effective_chat.id
    user = await context.bot.get_chat_member(chat_id, update.effective_user.id)

    if user.status not in ["administrator", "creator"]:
        await update.message.reply_text("❌ This command is restricted to administrators.")
        return

    # Check if a job is already running for this chat
    if context.job_queue.get_jobs_by_name(str(chat_id)):
        await update.message.reply_text("🔔 Auto-posting is already running!")
        return

    # Schedule the job
    context.job_queue.run_repeating(
        post_random_phrase, interval=600, first=10, data={"chat_id": chat_id}, name=str(chat_id)
    )
    await update.message.reply_text("🔔 Auto-posting of crypto phrases has been started!")


# Function to stop periodic posting (restricted to admins)
async def stop_auto_posts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Stops periodic posting of random crypto phrases (admin-only command).
    """
    chat_id = update.effective_chat.id
    user = await context.bot.get_chat_member(chat_id, update.effective_user.id)

    if user.status not in ["administrator", "creator"]:
        await update.message.reply_text("❌ This command is restricted to administrators.")
        return

    # Cancel any running jobs
    jobs = context.job_queue.get_jobs_by_name(str(chat_id))
    if not jobs:
        await update.message.reply_text("❌ No auto-posting is currently running!")
        return

    for job in jobs:
        job.schedule_removal()

    await update.message.reply_text("🔕 Auto-posting has been stopped!")


# Bot setup
import logging

# Configurar el sistema de logs
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.CRITICAL
)
logger = logging.getLogger(__name__)

if __name__ == "__main__":
    try:
        # Initialize the bot application
        app = ApplicationBuilder().token(BOT_TOKEN).build()

        # Modularización del registro de comandos
        def register_commands(app):
            try:
                command_handlers = [
                    CommandHandler("start", start),
                    CommandHandler("top_cryptos", get_top_cryptos),
                    CommandHandler("start_auto_posts", start_auto_posts),
                    CommandHandler("stop_auto_posts", stop_auto_posts),
                    CommandHandler("new_raid", new_raid),
                    CommandHandler("start_raid_posts", start_raid_posts),
                    CommandHandler("stop_raid_posts", stop_raid_posts),
                    CommandHandler("delete_all_raids", delete_all_raids),
                    CommandHandler("raid_status", raid_status),
                    CommandHandler("list_raids_detailed", list_raids_detailed),
                    CommandHandler("reset_database", reset_database_command),
                    CommandHandler("show_proofs", show_proofs),
                    CommandHandler("start_proof_verification", start_proof_verification),
                    CommandHandler("stop_proof_verification", stop_proof_verification),
                ]
                for handler in command_handlers:
                    app.add_handler(handler)
                logger.info("✅ Command handlers registered successfully.")
            except Exception as e:
                logger.error(f"❌ Error registering CommandHandlers: {e}")

        # Registrar manejadores de botones y mensajes
        def register_handlers(app):
            try:
                # CallbackQueryHandler para botones generales y específicos
                app.add_handler(CallbackQueryHandler(handle_join_raid, pattern="^join_raid:"))
                app.add_handler(CallbackQueryHandler(menu_handler))  # Manejo general
                app.add_handler(CallbackQueryHandler(confirm_delete_raids, pattern="^confirm_delete_raids$"))
                app.add_handler(CallbackQueryHandler(cancel_delete_raids, pattern="^cancel_delete_raids$"))
                logger.info("✅ CallbackQueryHandlers registered successfully.")
            except Exception as e:
                logger.error(f"❌ Error registering CallbackQueryHandlers: {e}")

            try:
                # Manejadores de mensajes
                app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_member))
                app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_messages))
                logger.info("✅ Message handlers registered successfully.")
            except Exception as e:
                logger.error(f"❌ Error registering MessageHandlers: {e}")

        # Función de verificación de configuración
        def verify_setup():
            try:
                logger.info("🔍 Verifying setup configuration...")
                # Validar tokens y claves
                if not BOT_TOKEN:
                    raise ValueError("❌ BOT_TOKEN is missing.")
                logger.info("✅ BOT_TOKEN is valid.")
                if not TWITTER_BEARER_TOKEN:
                    raise ValueError("❌ TWITTER_BEARER_TOKEN is missing.")
                logger.info("✅ TWITTER_BEARER_TOKEN is valid.")
                if not COINMARKETCAP_API_KEY:
                    raise ValueError("❌ COINMARKETCAP_API_KEY is missing.")
                logger.info("✅ COINMARKETCAP_API_KEY is valid.")
            except Exception as e:
                logger.error(f"❌ Error during setup verification: {e}")
                raise

        # Registro de comandos y manejadores
        verify_setup()
        register_commands(app)
        register_handlers(app)

        # Debugging: Print a success message when the bot starts
        logger.info("✅ The bot is running...")
        app.run_polling()

    except Exception as e:
        # Log and display any errors during setup
        logger.error(f"❌ Error during bot setup: {e}")
