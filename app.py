from flask import Flask, render_template, request, redirect, url_for, flash
import os
from werkzeug.utils import secure_filename
import fitz  # PyMuPDF para extraer texto de PDFs
import openai
from dotenv import load_dotenv

load_dotenv()  # Cargar variables de entorno desde un archivo .env

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads/'
app.config['ALLOWED_EXTENSIONS'] = {'pdf'}
app.secret_key = os.urandom(24)  # Genera una clave secreta aleatoria

openai.api_key = os.getenv('OPENAI_API_KEY')  # Clave API de OpenAI desde una variable de entorno

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

@app.route('/')
def upload_file():
    return render_template('upload.html')

@app.route('/uploader', methods=['GET', 'POST'])
def uploader_file():
    if request.method == 'POST':
        if 'rubric' not in request.files:
            flash('No se encontró la parte del archivo')
            return redirect(request.url)
        
        rubric_file = request.files['rubric']
        
        if rubric_file.filename == '':
            flash('No se seleccionó ningún archivo')
            return redirect(request.url)
        
        if rubric_file and allowed_file(rubric_file.filename):
            rubric_filename = secure_filename(rubric_file.filename)
            rubric_path = os.path.join(app.config['UPLOAD_FOLDER'], rubric_filename)
            rubric_file.save(rubric_path)
            
            # Verificar si el archivo es una rúbrica
            rubric_text = extract_text_from_pdf(rubric_path)
            is_rubric, _ = check_if_rubric(rubric_text)
            
            if not is_rubric:
                flash('El archivo cargado no es una rúbrica válida')
                return redirect(request.url)

            # Consultar a ChatGPT sobre la rúbrica
            measures = get_measures(rubric_text)
            points_type = get_points_type(rubric_text)
            total_points = get_total_points(rubric_text)

            return render_template('result.html', is_rubric=is_rubric, measures=measures, points_type=points_type, total_points=total_points)
        
        flash('Archivo no permitido')
        return redirect(request.url)

def extract_text_from_pdf(filepath):
    doc = fitz.open(filepath)
    text = ""
    for page in doc:
        text += page.get_text()
    return text

def check_if_rubric(text):
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are a file analysis tool. Your job is to determine whether the provided text is a rubric used for evaluation or not."},
                {"role": "user", "content": f"Evalua si este texto esta relacionado o no a una rubrica: {text[:3000]}"}
            ]
        )
        is_rubric = "Sí" in response.choices[0]['message']['content'] or "yes" in response.choices[0]['message']['content'].lower()
        return is_rubric, None  # Retornar None como segundo valor
    except Exception as e:
        print(f"Error al evaluar la rúbrica: {e}")
        return False, None  # Asegurarse de retornar dos valores

def get_measures(text):
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are a file analysis tool. Extract what is being measured in the provided rubric text."},
                {"role": "user", "content": f"¿Qué se está midiendo en esta rúbrica?: {text[:3000]}"}
            ]
        )
        measures = response.choices[0]['message']['content']
        return measures
    except Exception as e:
        print(f"Error al extraer las medidas: {e}")
        return []

def get_points_type(text):
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are a file analysis tool. Determine the type of points used in the provided rubric text."},
                {"role": "user", "content": f"¿Qué tipo de puntos se están utilizando en esta rúbrica?: {text[:3000]}"}
            ]
        )
        points_type = response.choices[0]['message']['content']
        return points_type
    except Exception as e:
        print(f"Error al determinar el tipo de puntos: {e}")
        return ""

def get_total_points(text):
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are a file analysis tool. Determine the total points measured in the provided rubric text."},
                {"role": "user", "content": f"¿Cuántos puntos en total se están midiendo en esta rúbrica?: {text[:3000]}"}
            ]
        )
        total_points = response.choices[0]['message']['content']
        return total_points
    except Exception as e:
        print(f"Error al extraer los puntos totales: {e}")
        return ""

if __name__ == '__main__':
    app.run(debug=True)
