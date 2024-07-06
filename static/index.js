// index.js

document.addEventListener('DOMContentLoaded', function () {
    const formSection = document.querySelector('.Formulario');
    const resultsSection = document.getElementById('Results');
    const submitButton = document.querySelector('.button');
    const form = document.querySelector('form');
    const estadoElement = document.getElementById('Estado');

    const estados = [
        "Cargando archivo...",
        "Analizando PDF...",
        "Analizando PPT...",
        "Extrayendo datos PPT...",
        "Realizando feedback..."
    ];

    let estadoIndex = 0;

    function updateEstado() {
        if (estadoIndex < estados.length) {
            estadoElement.textContent = estados[estadoIndex];
            estadoIndex++;
            if (estadoIndex < estados.length) {
                setTimeout(updateEstado, 7000); // Actualiza cada 7 segundos
            }
        }
    }

    submitButton.addEventListener('click', function (event) {
        event.preventDefault(); // Evita que el formulario se envíe inmediatamente
        formSection.classList.add('move-out');
        resultsSection.classList.remove('hidden');
        setTimeout(() => {
            resultsSection.classList.add('show');
            form.submit(); // Envía el formulario después de la animación
        }, 500); // 500ms coincide con la duración de la animación
        
        // Iniciar la actualización del estado
        updateEstado();
    });
});
