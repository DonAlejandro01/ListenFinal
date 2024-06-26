from flask import Flask, render_template, request, redirect, url_for, flash
import os
import io
from PIL import Image
from werkzeug.utils import secure_filename
import fitz  # PyMuPDF para extraer texto de PDFs
import openai
from dotenv import load_dotenv
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from google.cloud import vision
import logging

logging.basicConfig(level=logging.DEBUG)

# Cargar las variables de entorno desde el archivo .env
load_dotenv()

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads/'
app.config['ALLOWED_EXTENSIONS'] = {'pdf', 'ppt', 'pptx'}
app.secret_key = os.urandom(24)  # Genera una clave secreta aleatoria

openai.api_key = os.getenv('OPENAI_API_KEY')  # Clave API de OpenAI desde una variable de entorno

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

# Asegurarse de que la carpeta de subidas exista
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

@app.route('/')
def upload_file():
    return render_template('upload.html')

@app.route('/uploader', methods=['GET', 'POST'])
def uploader_file():
    if request.method == 'POST':
        if 'rubric' not in request.files and 'presentation' not in request.files:
            flash('No se encontró la parte del archivo')
            return redirect(request.url)

        rubric_file = request.files['rubric'] if 'rubric' in request.files else None
        presentation_file = request.files['presentation']
        user_type = request.form['user_type']
        presentation_theme = request.form['presentation_theme']
        presentation_type = request.form['presentation_type']
        presentation_goal = request.form['presentation_goal']

        if presentation_file.filename == '':
            flash('No se seleccionó ningún archivo de presentación')
            return redirect(request.url)

        if user_type != 'other' and (not rubric_file or rubric_file.filename == ''):
            flash('No se seleccionó ningún archivo de rúbrica')
            return redirect(request.url)

        if presentation_file and allowed_file(presentation_file.filename):
            presentation_filename = secure_filename(presentation_file.filename)
            presentation_path = os.path.join(app.config['UPLOAD_FOLDER'], presentation_filename)
            presentation_file.save(presentation_path)
            
            # Si el perfil del usuario no es "other", se procede con la evaluación de la rúbrica
            if user_type != 'other' and rubric_file and allowed_file(rubric_file.filename):
                rubric_filename = secure_filename(rubric_file.filename)
                rubric_path = os.path.join(app.config['UPLOAD_FOLDER'], rubric_filename)
                rubric_file.save(rubric_path)
                
                rubric_text = extract_text_from_pdf(rubric_path)
                is_rubric, _ = check_if_rubric(rubric_text)
                
                if not is_rubric:
                    flash('El archivo cargado no es una rúbrica válida')
                    return redirect(request.url)

                measures = get_measures(rubric_text)
                points_type = get_points_type(rubric_text)
                max_score = calculate_total_score(measures, points_type)  # Calcular el puntaje máximo

                presentation_text = extract_text_from_ppt(presentation_path)
                titles = extract_titles(presentation_path)
                subtitles = extract_subtitles(presentation_path)
                body_texts = extract_body_texts(presentation_path, titles, subtitles)
                images = extract_images(presentation_path)
                analyzed_images = [analyze_image_google_cloud(slide_idx, image) for slide_idx, image in images]

                total_score, feedback_list = evaluate_presentation_by_measures(presentation_text, measures, points_type, titles, subtitles, body_texts, analyzed_images)

                grade = convert_score_to_grade(total_score, max_score)  # Convertir el puntaje total en una nota

                if grade == 7:
                    feedback_list.append("Felicidades, has obtenido una nota perfecta. ¡Excelente trabajo!")

                return render_template('result.html', presentation_score=grade, feedback=feedback_list)
            else:
                # Si el perfil del usuario es "other", solo se extraen los datos y se proporciona feedback
                presentation_text = extract_text_from_ppt(presentation_path)
                titles = extract_titles(presentation_path)
                subtitles = extract_subtitles(presentation_path)
                body_texts = extract_body_texts(presentation_path, titles, subtitles)
                images = extract_images(presentation_path)
                analyzed_images = [analyze_image_google_cloud(slide_idx, image) for slide_idx, image in images]

                feedback = generate_feedback_for_other(presentation_theme, presentation_type, presentation_goal, titles, subtitles, body_texts, analyzed_images)
                feedback_list = [item.strip() for item in feedback.split('\n') if item.strip()]
                
                return render_template('result.html', presentation_score="N/A", feedback=feedback_list)
        
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
                {"role": "user", "content": f"Evalua si este texto está relacionado o no a una rúbrica: {text[:3000]}"}
            ]
        )
        is_rubric = "Sí" in response['choices'][0]['message']['content'] or "yes" in response['choices'][0]['message']['content'].lower()
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
                {"role": "user", "content": f"Extrae los enunciados de la rúbrica del siguiente texto. Solo proporciona los títulos de las categorías evaluadas, sin frase introductoria, sin frase de conclusión, sin descripción, ni valores numéricos, ni caracteres especiales. Proporciona cada título en una nueva línea: {text[:3000]}"}
            ]
        )
        measures = response['choices'][0]['message']['content']
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
        points_content = response['choices'][0]['message']['content'].strip()
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

def extract_titles(filepath):
    prs = Presentation(filepath)
    titles = []

    for slide in prs.slides:
        for shape in slide.shapes:
            if shape.has_text_frame:
                title = shape.text_frame.text
                if title:
                    titles.append(title)
                    break

    # Imprimir los títulos extraídos en la consola
    for index, title in enumerate(titles):
        print(f"Slide {index + 1}: {title}")

    return titles

def extract_subtitles(filepath):
    prs = Presentation(filepath)
    subtitles = []

    for slide in prs.slides:
        subtitle_found = False
        for shape in slide.shapes:
            if shape.has_text_frame and not subtitle_found:
                paragraphs = shape.text_frame.paragraphs
                if len(paragraphs) > 1:
                    subtitles.append(paragraphs[1].text)
                    subtitle_found = True

        if not subtitle_found:
            subtitles.append("")

    # Imprimir los subtítulos extraídos en la consola
    for index, subtitle in enumerate(subtitles):
        print(f"Slide {index + 1}: {subtitle}")

    return subtitles

def extract_body_texts(filepath, titles, subtitles):
    prs = Presentation(filepath)
    body_texts = []

    for slide_idx, slide in enumerate(prs.slides):
        body_text = []
        for shape in slide.shapes:
            if not shape.has_text_frame:
                continue
            for paragraph in shape.text_frame.paragraphs:
                for run in paragraph.runs:
                    font_size = run.font.size
                    text = run.text.strip()
                    if font_size and font_size < 2400000 and text not in titles and text not in subtitles:
                        body_text.append(text)
        body_texts.append('\n'.join(body_text))

    # Imprimir los textos del cuerpo extraídos en la consola
    for index, body_text in enumerate(body_texts):
        print(f"Slide {index + 1} Body Text:\n{body_text}\n")

    return body_texts

def extract_images(filepath):
    prs = Presentation(filepath)
    images = []

    for slide_idx, slide in enumerate(prs.slides, start=1):
        for shape in slide.shapes:
            if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                image = shape.image
                image_bytes = io.BytesIO(image.blob)
                pil_image = Image.open(image_bytes)
                images.append((slide_idx, pil_image))  # Incluir el número de diapositiva y la imagen

    return images


def analyze_image_google_cloud(slide_idx, image):
    client = vision.ImageAnnotatorClient()
    img_byte_arr = io.BytesIO()
    image.save(img_byte_arr, format='PNG')
    content = img_byte_arr.getvalue()

    image = vision.Image(content=content)
    response = client.label_detection(image=image)
    labels = response.label_annotations

    analyzed_image_info = ', '.join([label.description for label in labels])
    print(f"Slide {slide_idx}: {analyzed_image_info}")  # Incluir el número de diapositiva en la impresión
    
    return slide_idx, analyzed_image_info  # Devolver el número de diapositiva junto con la información analizada


def evaluate_presentation_by_measures(presentation_text, measures, points_type, titles, subtitles, body_texts, analyzed_images):
    try:
        measures_str = "\n".join(measures)
        points_str = ", ".join(map(str, points_type))
        titles_str = "\n".join(titles)
        subtitles_str = "\n".join(subtitles)
        body_texts_str = "\n".join(body_texts)
        images_info_str = "\n".join([f"Slide {idx}: {info}" for idx, info in analyzed_images])

        prompt = f"""
        Evalúa la siguiente presentación basada en las medidas y tipos de puntos proporcionados. Proporciona un puntaje para cada medida y un feedback general con recomendaciones para mejorar:

        Medidas:
        {measures_str}

        Tipos de puntos:
        {points_str}

        Títulos:
        {titles_str}

        Subtítulos:
        {subtitles_str}

        Textos del cuerpo:
        {body_texts_str}

        Información de las imágenes:
        {images_info_str}

        Texto de la presentación:
        {presentation_text[:3000]}
        """

        print(f"Prompt enviado a OpenAI: {prompt}")  # Imprimir el prompt para verificar su contenido
        
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are an evaluation tool. Your job is to evaluate the provided presentation text based on the given rubric measures and point types, and provide scores for each measure and general feedback as the result."},
                {"role": "user", "content": prompt}
            ]
        )

        response_content = response['choices'][0]['message']['content'].strip()
        print(f"Respuesta de OpenAI: {response_content}")  # Imprimir la respuesta para verificar su contenido

        # Procesar la respuesta para extraer puntajes y feedback
        lines = response_content.split("\n")
        scores = {}
        feedback_lines = []
        for line in lines:
            if ":" in line:
                measure, score = line.split(":")
                measure = measure.strip()
                try:
                    score = int(score.strip().split("/")[0])
                    scores[measure] = score
                except ValueError:
                    # En caso de no poder convertir el puntaje, lo consideramos 0
                    scores[measure] = 0
            else:
                feedback_lines.append(line)

        feedback_list = [item.strip() for item in feedback_lines if item.strip()]

        # Calcular el puntaje total
        total_score = sum(scores.values())

        return total_score, feedback_list
    except Exception as e:
        print(f"Error al evaluar la presentación: {e}")
        return 0, ["Error en la evaluación de la presentación."]

def convert_score_to_grade(total_score, max_score):
    if max_score == 0:
        return 0  # Evitar división por cero
    percentage = total_score / max_score
    if percentage >= 0.9:
        return 7
    elif percentage >= 0.8:
        return 6
    elif percentage >= 0.7:
        return 5
    elif percentage >= 0.6:
        return 4
    elif percentage >= 0.5:
        return 3
    elif percentage >= 0.4:
        return 2
    else:
        return 1
    

def generate_feedback_for_other(theme, p_type, goal, titles, subtitles, body_texts, images_info):
    prompt = f"""
    Tema de la presentación: {theme}
    Tipo de presentación: {p_type}
    Objetivo de la presentación: {goal}
    
    Títulos: {', '.join(titles)}
    Subtítulos: {', '.join(subtitles)}
    Textos del cuerpo: {', '.join(body_texts)}
    Información de las imágenes: {', '.join(info for _, info in images_info)}

    Basado en la información anterior, proporciona recomendaciones para mejorar la presentación y asegurar que sea excelente.
    """

    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "You are an evaluation assistant. Your job is to provide feedback to improve the presentation based on the provided details."},
            {"role": "user", "content": prompt}
        ]
    )

    feedback = response['choices'][0]['message']['content'].strip()
    return feedback

if __name__ == '__main__':
    app.run(debug=True)
