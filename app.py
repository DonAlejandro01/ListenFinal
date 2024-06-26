from flask import Flask, render_template, request, redirect, url_for, flash
import os
from werkzeug.utils import secure_filename
import fitz  # PyMuPDF para extraer texto de PDFs
import openai
from dotenv import load_dotenv
from pptx import Presentation

load_dotenv()  # Cargar variables de entorno desde un archivo .env

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads/'
app.config['ALLOWED_EXTENSIONS'] = {'pdf', 'ppt', 'pptx'}
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
        if 'rubric' not in request.files or 'presentation' not in request.files:
            flash('No se encontró la parte del archivo')
            return redirect(request.url)
        
        rubric_file = request.files['rubric']
        presentation_file = request.files['presentation']
        required_score = request.form.get('required_score')
        
        if rubric_file.filename == '' or presentation_file.filename == '':
            flash('No se seleccionó ningún archivo')
            return redirect(request.url)
        
        if rubric_file and allowed_file(rubric_file.filename) and presentation_file and allowed_file(presentation_file.filename):
            rubric_filename = secure_filename(rubric_file.filename)
            presentation_filename = secure_filename(presentation_file.filename)
            rubric_path = os.path.join(app.config['UPLOAD_FOLDER'], rubric_filename)
            presentation_path = os.path.join(app.config['UPLOAD_FOLDER'], presentation_filename)
            rubric_file.save(rubric_path)
            presentation_file.save(presentation_path)
            
            # Verificar si el archivo es una rúbrica
            rubric_text = extract_text_from_pdf(rubric_path)
            is_rubric, _ = check_if_rubric(rubric_text)
            
            if not is_rubric:
                flash('El archivo cargado no es una rúbrica válida')
                return redirect(request.url)

            # Consultar a ChatGPT sobre la rúbrica
            measures = get_measures(rubric_text)
            points_type = get_points_type(rubric_text)
            total_score = calculate_total_score(measures, points_type)

            # Extraer texto de la presentación PPT
            presentation_text = extract_text_from_ppt(presentation_path)

            # Evaluar la presentación
            presentation_score = evaluate_presentation(presentation_text, measures, points_type)

            return render_template('result.html', is_rubric=is_rubric, measures=measures, points_type=points_type, total_score=total_score, required_score=required_score, presentation_score=presentation_score)
        
        flash('Archivo no permitido')
        return redirect(request.url)
    else:
        return render_template('upload.html')

def extract_text_from_pdf(filepath):
    doc = fitz.open(filepath)
    text = ""
    for page in doc:
        text += page.get_text()
    print(text)  # Imprimir el texto extraído en la consola
    return text

def extract_text_from_ppt(filepath):
    prs = Presentation(filepath)
    text_runs = []
    for slide in prs.slides:
        for shape in slide.shapes:
            if hasattr(shape, "text"):
                text_runs.append(shape.text)
    return "\n".join(text_runs)

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
                {"role": "system", "content": "You are a file analysis tool. Your job is to extract the rubric statements from the provided text. Each statement describes an aspect of the presentation that is being evaluated."},
                {"role": "user", "content": f"Extrae los enunciados de la rúbrica del siguiente texto. Solo proporciona los títulos de las categorías evaluadas,sin frase introductorio,sin frase de conclusion, sin descripción, ni valores numéricos, ni caracteres especiales. Proporciona cada título en una nueva línea: {text[:3000]}"}
            ]
        )
        # Parse the response to extract the enunciados
        measures = response.choices[0]['message']['content']
        measures_list = [measure.strip() for measure in measures.split('\n') if measure.strip()]
        return measures_list
    except Exception as e:
        print(f"Error al extraer las medidas: {e}")
        return []   
    
def get_points_type(text):
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are a file analysis tool. Determine the type of points used in the provided rubric text and list them in descending order."},
                {"role": "user", "content": f"Extrae el tipo de puntos que se están utilizando en esta rúbrica. No me des texto introductorio, ni de conclusión, ni tampoco descripción. Solo proporciona los valores numéricos en orden descendente: {text[:3000]}"}
            ]
        )
        points_content = response.choices[0]['message']['content'].strip()
        # Convert the response to a list of numbers
        points_list = [int(point.strip()) for point in points_content.split(',')]
        return sorted(points_list, reverse=True)
    except Exception as e:
        print(f"Error al determinar el tipo de puntos: {e}")
        return []

def calculate_total_score(measures, points_type):
    if not measures or not points_type:
        return 0
    max_point = max(points_type)
    total_score = len(measures) * max_point
    return total_score

def evaluate_presentation(presentation_text, measures, points_type):
    try:
        measures_str = "\n".join(measures)
        points_str = ", ".join(map(str, points_type))
        prompt = f"Evalúa la siguiente presentación basada en las siguientes medidas y puntajes. Solo proporciona un número como resultado:\n\nMedidas:\n{measures_str}\n\nTipos de puntos:\n{points_str}\n\nTexto de la presentación:\n{presentation_text[:3000]}"
        
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are an evaluation tool. Your job is to evaluate the provided presentation text based on the given rubric measures and point types, and provide a numerical score as the result."},
                {"role": "user", "content": prompt}
            ]
        )
        
        # Intentar extraer un número de la respuesta
        response_content = response.choices[0]['message']['content'].strip()
        score = int(response_content.split()[0])  # Extraer el primer número de la respuesta
        return score
    except Exception as e:
        print(f"Error al evaluar la presentación: {e}")
        return 0

if __name__ == '__main__':
    app.run(debug=True)
