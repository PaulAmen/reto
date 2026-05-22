/* ==========================================================================
   SATIE Frontend Core Logic — Test Harness & Live Dashboard Simulator
   ========================================================================== */

const API_BASE_URL = localStorage.getItem('satie_api_base_url') !== null 
    ? localStorage.getItem('satie_api_base_url') 
    : (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1' ? 'http://localhost:8080' : '');
const WEBHOOK_SECRET = localStorage.getItem('satie_webhook_secret') || '';
let aseguradosDemo = [];
let casosProcesados = {};
let pollingInterval = null;

// Sugerencias clínicas y signos vitales realistas por asegurado para hacer el demo dinámico
const SUGERENCIAS_CASOS = {
    "1312045678": { // María Fernanda Cedeño (Premium)
        motivo: "Dolor abdominal agudo en fosa ilíaca derecha de 12 horas de evolución, sospecha de apendicitis aguda.",
        triaje: "Amarillo",
        sv: { presion: "120/80", fc: 88, sato2: 98 }
    },
    "1305887421": { // Jorge Luis Macías (Hipertensión/Cardiopatía)
        motivo: "Dolor torácico opresivo de 2 horas de evolución irradiado a cuello y brazo izquierdo, acompañado de disnea leve.",
        triaje: "Rojo",
        sv: { presion: "160/100", fc: 110, sato2: 94 }
    },
    "1314562089": { // Carla Vanessa Pin (En mora 2 meses)
        motivo: "Cefalea intensa y repentina con alteración visual temporal y adormecimiento en extremidades superiores.",
        triaje: "Naranja",
        sv: { presion: "140/90", fc: 95, sato2: 97 }
    },
    "1309774530": { // Roberto Andrés Quimís (Vencida 2 meses)
        motivo: "Fractura expuesta de tibia y peroné izquierdo tras caída accidental de altura aproximada de 2 metros.",
        triaje: "Naranja",
        sv: { presion: "130/85", fc: 92, sato2: 98 }
    },
    "1318903247": { // Andrea Paola Vera (Nueva, diabetes, carencia)
        motivo: "Cetoacidosis diabética descompensada: paciente deshidratada, aliento cetónico y somnolencia progresiva.",
        triaje: "Rojo",
        sv: { presion: "105/65", fc: 115, sato2: 95 }
    },
    "1311456722": { // Génesis Mariuxi Loor (Maternidad, alto riesgo)
        motivo: "Contracciones uterinas dolorosas y frecuentes en semana 34 de gestación de alto riesgo, con pérdida leve de líquido.",
        triaje: "Rojo",
        sv: { presion: "135/85", fc: 98, sato2: 96 }
    },
    "1307889104": { // Luis Alberto Parrales (Asma, fuera de carencia)
        motivo: "Crisis asmática severa y sibilancias bilaterales audibles que no responden al uso de broncodilatadores habituales.",
        triaje: "Rojo",
        sv: { presion: "125/80", fc: 105, sato2: 91 }
    },
    "1316240985": { // Diana Carolina Chóez (Premium, amplia)
        motivo: "Fiebre persistente de 39.2°C de 48 horas de evolución, tos productiva y disnea leve.",
        triaje: "Amarillo",
        sv: { presion: "115/75", fc: 90, sato2: 96 }
    },
    "1303661278": { // Marco Antonio Bravo (Mora de 5 meses)
        motivo: "Cólico renal agudo persistente y muy doloroso en flanco derecho acompañado de náuseas y hematuria microscópica.",
        triaje: "Amarillo",
        sv: { presion: "135/85", fc: 85, sato2: 99 }
    },
    "1319075463": { // Verónica Estefanía Mendoza (Cáncer mama, carencia)
        motivo: "Dolor óseo generalizado de inicio súbito y fatiga extrema tras tratamiento oncológico, con sospecha de neutropenia febril.",
        triaje: "Rojo",
        sv: { presion: "110/70", fc: 102, sato2: 95 }
    }
};

document.addEventListener('DOMContentLoaded', () => {
    initApp();
});

function initApp() {
    setupCollapsible();
    verificarEstadoApi();
    cargarAsegurados();
    iniciarLivePolling();
    
    // Configurar listener para el formulario
    document.getElementById('webhook-form').addEventListener('submit', enviarWebhook);
}

async function verificarEstadoApi() {
    const statusText = document.getElementById('api-status-text');
    const statusDot = document.getElementById('api-status-dot');
    try {
        const response = await fetch(`${API_BASE_URL}/health`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        statusText.textContent = 'Online';
        statusDot.classList.add('online');
        statusDot.classList.remove('offline');
    } catch (error) {
        statusText.textContent = 'Offline';
        statusDot.classList.add('offline');
        statusDot.classList.remove('online');
        mostrarErrorConexion();
    }
}

function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, char => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;'
    }[char]));
}

function formatUsd(value) {
    return new Intl.NumberFormat('es-EC', {
        style: 'currency',
        currency: 'USD',
        maximumFractionDigits: 0
    }).format(Number(value || 0));
}

// Configurar panel de respuesta técnica colapsable
function setupCollapsible() {
    const toggle = document.getElementById('tech-resp-toggle');
    const box = document.getElementById('tech-resp-box');
    
    toggle.addEventListener('click', () => {
        box.classList.toggle('collapsed');
    });
}

// 1. Cargar catálogo de asegurados para el simulador
async function cargarAsegurados() {
    const selector = document.getElementById('poliza-selector');
    try {
        const response = await fetch(`${API_BASE_URL}/asegurados`);
        if (!response.ok) throw new Error('Error al obtener asegurados demo');
        
        aseguradosDemo = await response.json();
        
        // Limpiar el selector y rellenar
        selector.innerHTML = '<option value="" disabled selected>-- Selecciona un Asegurado para el Demo --</option>';
        
        aseguradosDemo.forEach(asegurado => {
            const opt = document.createElement('option');
            opt.value = asegurado.cedula;
            opt.textContent = `${asegurado.nombre} (C.I. ${asegurado.cedula}) — ${asegurado.plan}`;
            selector.appendChild(opt);
        });

        // Configurar prellenado al cambiar selección
        selector.addEventListener('change', (e) => {
            const cedula = e.target.value;
            const pol = aseguradosDemo.find(p => p.cedula === cedula);
            prellenarFormulario(pol);
        });
        
    } catch (error) {
        console.error('Error cargando asegurados:', error);
        selector.innerHTML = '<option value="" disabled>Error al conectar con la API</option>';
        mostrarErrorConexion();
    }
}

// Prellenar el formulario del simulador
function prellenarFormulario(poliza) {
    if (!poliza) return;

    // Campos básicos
    document.getElementById('paciente-nombre').value = poliza.nombre;
    document.getElementById('paciente-cedula').value = poliza.cedula;
    document.getElementById('evento-id').value = `evt-${Math.floor(100000 + Math.random() * 900000)}`;

    // Seleccionar primer hospital de la red si existe
    if (poliza.hospitales_red && poliza.hospitales_red.length > 0) {
        document.getElementById('hospital-nombre').value = poliza.hospitales_red[0];
    } else {
        document.getElementById('hospital-nombre').value = "Hospital Metropolitano del Sur";
    }

    // Cargar sugerencia clínica preconfigurada
    const sugerencia = SUGERENCIAS_CASOS[poliza.cedula];
    if (sugerencia) {
        document.getElementById('motivo-ingreso').value = sugerencia.motivo;
        document.getElementById('triaje-hospital').value = sugerencia.triaje;
        document.getElementById('sv-presion').value = sugerencia.sv.presion;
        document.getElementById('sv-fc').value = sugerencia.sv.fc;
        document.getElementById('sv-sato2').value = sugerencia.sv.sato2;
    } else {
        document.getElementById('motivo-ingreso').value = "Ingreso general por malestar agudo.";
        document.getElementById('triaje-hospital').value = "Amarillo";
        document.getElementById('sv-presion').value = "120/80";
        document.getElementById('sv-fc').value = 75;
        document.getElementById('sv-sato2').value = 98;
    }

    // Mostrar descripción de ayuda sobre el caso seleccionado
    const helpText = document.getElementById('poliza-desc-help');
    helpText.innerHTML = `🛡️ <b>Caso Demo:</b> ${poliza.descripcion_caso || 'Sin observaciones.'}`;
    helpText.style.color = '#38bdf8'; // light blue highlights
}

// 2. Enviar Webhook
async function enviarWebhook(e) {
    e.preventDefault();
    
    const btnSubmit = document.getElementById('btn-submit-admission');
    const spinner = document.getElementById('webhook-spinner');
    const techBox = document.getElementById('tech-resp-box');
    const jsonCode = document.getElementById('json-response-code');
    
    // Activar spinner
    btnSubmit.disabled = true;
    spinner.classList.remove('hidden');
    
    // Obtener valores
    const evento_id = document.getElementById('evento-id').value.trim() || undefined;
    const cedula = document.getElementById('paciente-cedula').value.trim();
    const nombre_paciente = document.getElementById('paciente-nombre').value.trim();
    const motivo_ingreso = document.getElementById('motivo-ingreso').value.trim();
    const hospital = document.getElementById('hospital-nombre').value.trim();
    const triaje_hospital = document.getElementById('triaje-hospital').value;
    
    const sv_presion = document.getElementById('sv-presion').value.trim() || null;
    const sv_fc = document.getElementById('sv-fc').value ? parseInt(document.getElementById('sv-fc').value) : null;
    const sv_sato2 = document.getElementById('sv-sato2').value ? parseInt(document.getElementById('sv-sato2').value) : null;

    const payload = {
        cedula,
        nombre_paciente,
        motivo_ingreso,
        hospital,
        triaje_hospital,
        signos_vitales: (sv_presion || sv_fc || sv_sato2) ? {
            presion_arterial: sv_presion,
            frecuencia_cardiaca: sv_fc,
            saturacion_oxigeno: sv_sato2
        } : null
    };
    
    if (evento_id) {
        payload.evento_id = evento_id;
    }

    try {
        const response = await fetch(`${API_BASE_URL}/webhook/emergencia`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                ...(WEBHOOK_SECRET ? { 'X-Webhook-Secret': WEBHOOK_SECRET } : {})
            },
            body: JSON.stringify(payload)
        });

        const data = await response.json();
        
        // Mostrar en el bloque de código JSON
        jsonCode.textContent = JSON.stringify(data, null, 2);
        techBox.classList.remove('collapsed'); // expandir automáticamente
        
        // Disparar recarga manual inmediata para actualizar los paneles en vivo
        await recargarCasos();
        
    } catch (error) {
        console.error('Error enviando webhook:', error);
        jsonCode.textContent = `Error al conectar con el servidor:\n${error.message}`;
        techBox.classList.remove('collapsed');
    } finally {
        btnSubmit.disabled = false;
        spinner.classList.add('hidden');
    }
}

// 3. Sondeo en Vivo (Polling) de casos
function iniciarLivePolling() {
    recargarCasos();
    // Poll cada 2.5 segundos para tener respuesta casi instantánea
    pollingInterval = setInterval(recargarCasos, 2500);
}

async function recargarCasos() {
    try {
        const response = await fetch(`${API_BASE_URL}/casos`);
        if (!response.ok) throw new Error('Error al consultar casos');
        
        const data = await response.json();
        
        // Verificar si hay cambios reales para evitar re-renderizaciones innecesarias
        if (JSON.stringify(casosProcesados) !== JSON.stringify(data)) {
            casosProcesados = data;
            renderizarCasos(casosProcesados);
        }
    } catch (error) {
        console.error('Error al actualizar casos en vivo:', error);
    }
}

// 4. Renderizar las tarjetas en los paneles
function renderizarCasos(casos) {
    const listAdmisiones = document.getElementById('admissions-list');
    const listGestor = document.getElementById('cases-list');
    
    // Obtener casos como array y ordenar por fecha de recepción descendente (más nuevos arriba)
    const arrayCasos = Object.values(casos).sort((a, b) => {
        return new Date(b.recibido_en) - new Date(a.recibido_en);
    });

    if (arrayCasos.length === 0) {
        return; // Mantener estados vacíos iniciales
    }

    // Limpiar listas
    listAdmisiones.innerHTML = '';
    listGestor.innerHTML = '';

    arrayCasos.forEach(caso => {
        const pac = caso.paciente;
        const ev = caso.evaluacion_poliza;
        const an = caso.analisis_agente;
        const nombrePaciente = escapeHtml(pac.nombre_paciente);
        const cedula = escapeHtml(pac.cedula);
        const hospital = escapeHtml(pac.hospital);
        const motivoIngreso = escapeHtml(pac.motivo_ingreso);
        const eventoId = escapeHtml(caso.evento_id);
        const estadoCobertura = escapeHtml(an.estado_cobertura_presunta);
        const nivelTriaje = escapeHtml(an.nivel_triaje);
        const mensajeAdmisiones = escapeHtml(an.mensaje_admisiones_hospital);
        const mensajeGestor = escapeHtml(an.mensaje_gestor_seguro);
        const detallePreexistencia = escapeHtml(an.detalle_preexistencia);
        
        // Formatear fecha para lectura humana
        const fechaObj = new Date(caso.recibido_en);
        const horaHuman = fechaObj.toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit', second: '2-digit' });

        // Determinación de colores del triaje
        const triajeColorClass = obtenerClaseTriaje(an.nivel_triaje);
        const triajeText = nivelTriaje;

        // --- TARJETA 1: ADMISIONES HOSPITAL ---
        const cardAdmissions = document.createElement('div');
        cardAdmissions.className = `live-card border-${triajeColorClass}`;
        
        // Construir contenido para hospital
        cardAdmissions.innerHTML = `
            <div class="card-header-row">
                <div class="card-title-group">
                    <h3>${nombrePaciente}</h3>
                    <p><i class="fa-solid fa-clock"></i> Ingreso: ${horaHuman} | C.I. ${cedula}</p>
                </div>
                <div class="card-badge-group">
                    <span class="badge-triaje bg-${triajeColorClass}">${triajeText}</span>
                    <span class="badge-cobertura ${estadoCobertura}">${estadoCobertura.replace('_', ' ')}</span>
                </div>
            </div>

            <div class="card-details">
                <div class="detail-item">
                    <span class="label">Hospital</span>
                    <span class="val">${hospital}</span>
                </div>
                <div class="detail-item">
                    <span class="label">Póliza</span>
                    <span class="val">${escapeHtml(ev.validez)}</span>
                </div>
                <div class="detail-item full-width">
                    <span class="label">Motivo de ingreso</span>
                    <span class="val">${motivoIngreso}</span>
                </div>
            </div>

            <div class="gemini-feedback-box">
                <b>Indicación Operativa:</b><br>
                ${mensajeAdmisiones}
            </div>
            
            <div style="font-size: 9px; color: var(--text-muted); text-align: right; margin-top:-4px;">
                ID: ${eventoId}
            </div>
        `;
        listAdmisiones.appendChild(cardAdmissions);

        // --- TARJETA 2: GESTOR DE CASOS ASEGURADORA ---
        const cardGestor = document.createElement('div');
        cardGestor.className = `live-card border-${triajeColorClass}`;
        
        // Construir acciones recomendadas
        let accionesHtml = '';
        if (an.acciones_recomendadas && an.acciones_recomendadas.length > 0) {
            accionesHtml = `
                <div class="actions-box">
                    <h5><i class="fa-solid fa-clipboard-list"></i> Tareas Recomendadas</h5>
                    <ul class="action-list">
                        ${an.acciones_recomendadas.map(ac => `
                            <li class="action-item">
                                <i class="fa-regular fa-square-check"></i>
                                <span>${escapeHtml(ac)}</span>
                            </li>
                        `).join('')}
                    </ul>
                </div>
            `;
        }

        // Construir contenido para gestor
        cardGestor.innerHTML = `
            <div class="card-header-row">
                <div class="card-title-group">
                    <h3>${nombrePaciente}</h3>
                    <p><i class="fa-solid fa-clock"></i> C.I. ${cedula} | Plan: ${caso.poliza ? escapeHtml(caso.poliza.plan) : 'N/A'}</p>
                </div>
                <div class="card-badge-group">
                    <span class="badge ${obtenerBadgeRiesgo(an.riesgo_siniestro)}">Riesgo ${escapeHtml(an.riesgo_siniestro)}</span>
                    <span class="badge-cobertura ${estadoCobertura}">${estadoCobertura.replace('_', ' ')}</span>
                </div>
            </div>

            <div class="card-details">
                <div class="detail-item">
                    <span class="label">Aseguradora</span>
                    <span class="val">${caso.poliza ? escapeHtml(caso.poliza.aseguradora) : 'Desconocida'}</span>
                </div>
                <div class="detail-item">
                    <span class="label">Cobertura / Deducible (USD)</span>
                    <span class="val">${caso.poliza ? formatUsd(caso.poliza.suma_asegurada) : 'USD 0'} / ${caso.poliza ? formatUsd(caso.poliza.deducible) : 'USD 0'}</span>
                </div>
                <div class="detail-item full-width">
                    <span class="label">Preexistencia Relacionada</span>
                    <span class="val" style="color: ${an.preexistencia_relacionada ? 'var(--triaje-critico)' : 'var(--triaje-leve)'}">
                        ${an.preexistencia_relacionada ? 'SÍ' : 'NO'} | ${detallePreexistencia}
                    </span>
                </div>
                <div class="detail-item">
                    <span class="label">Carencia General</span>
                    <span class="val">${ev.dentro_carencia_general ? 'DENTRO (Excluido)' : 'FUERA'}</span>
                </div>
                <div class="detail-item">
                    <span class="label">Carencia Preex.</span>
                    <span class="val" style="color: ${an.aplica_periodo_carencia ? 'var(--triaje-critico)' : 'var(--text-secondary)'}">
                        ${ev.dentro_carencia_preexistencias ? 'SÍ (Aplica carencia)' : 'NO'}
                    </span>
                </div>
            </div>

            <div class="gemini-feedback-box" style="font-size: 11px; background: hsla(250, 80%, 45%, 0.05); border-color: hsla(250, 80%, 45%, 0.12);">
                <b>Análisis del Caso:</b><br>
                ${mensajeGestor}
            </div>

            ${accionesHtml}
        `;
        listGestor.appendChild(cardGestor);
    });
}

// Helpers para formatos visuales en base a triajes y riesgos
function obtenerClaseTriaje(nivel) {
    const n = nivel.toUpperCase();
    if (n === 'CRITICO' || n === 'ROJO') return 'critico';
    if (n === 'URGENTE' || n === 'NARANJA') return 'urgente';
    if (n === 'MODERADO' || n === 'AMARILLO') return 'moderado';
    return 'leve'; // LEVE / VERDE
}

function obtenerBadgeRiesgo(riesgo) {
    const r = riesgo.toUpperCase();
    if (r === 'ALTO') return 'badge-triaje bg-critico';
    if (r === 'MEDIO') return 'badge-triaje bg-urgente';
    return 'badge-triaje bg-leve'; // BAJO
}

function mostrarErrorConexion() {
    const listAdmisiones = document.getElementById('admissions-list');
    const listGestor = document.getElementById('cases-list');
    
    const msg = `
        <div class="empty-state">
            <i class="fa-solid fa-triangle-exclamation" style="color: var(--triaje-critico)"></i>
            <p>Servidor Desconectado</p>
            <small>Asegúrate de que la API de FastAPI esté levantada en el puerto 8080 (http://localhost:8080).</small>
        </div>
    `;
    listAdmisiones.innerHTML = msg;
    listGestor.innerHTML = msg;
}
