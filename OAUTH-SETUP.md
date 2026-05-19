# Configurar OAuth de Google y GitHub

Para que los usuarios puedan loguearse con Google y GitHub necesitas crear "OAuth Apps"
en cada plataforma. Es gratis y toma 10 minutos en total.

---

## 🔵 Google OAuth (5 min)

### 1. Crear el proyecto OAuth
1. Ve a https://console.cloud.google.com
2. Si no tienes proyecto, crea uno: arriba a la izquierda **"Seleccionar proyecto" → "Proyecto nuevo"** → nombre: `JARVIS` → CREAR.

### 2. Configurar pantalla de consentimiento
1. Menú lateral: **APIs y servicios → Pantalla de consentimiento de OAuth**
2. Tipo de usuario: **Externo** → CREAR
3. Rellena:
   - Nombre de la aplicación: **JARVIS**
   - Email de asistencia al usuario: tu correo
   - Email del desarrollador: tu correo
4. GUARDAR Y CONTINUAR (los siguientes pasos: GUARDAR Y CONTINUAR)
5. Al final → **VOLVER AL PANEL**
6. (Solo en modo testing) En **"Usuarios de prueba"** → AGREGAR → tu propio email + de quienes vayan a probar

### 3. Crear credenciales OAuth
1. Menú lateral: **APIs y servicios → Credenciales**
2. **+ CREAR CREDENCIALES → ID de cliente OAuth**
3. **Tipo de aplicación: Aplicación web**
4. Nombre: `JARVIS Backend`
5. En **URIs de redireccionamiento autorizados**, agrega:
   - `http://localhost:8000/auth/google/callback` (dev)
   - `https://tu-dominio-railway.up.railway.app/auth/google/callback` (prod — agregarlo después)
6. CREAR
7. **Copia el Client ID y Client Secret** que te aparecen

### 4. Pegar en el .env
Edita `C:\Users\demzy\Desktop\JARVIS-Cloud\backend\.env`:
```
GOOGLE_CLIENT_ID=123456789-abc...apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-...
```

---

## ⬛ GitHub OAuth (3 min)

### 1. Crear OAuth App
1. Ve a https://github.com/settings/applications/new
2. Rellena:
   - **Application name:** JARVIS
   - **Homepage URL:** `http://localhost:8000` (o tu dominio cuando lo tengas)
   - **Authorization callback URL:** `http://localhost:8000/auth/github/callback`
3. **Register application**
4. En la siguiente página, **Generate a new client secret**
5. **Copia el Client ID y el Client Secret** (el secret solo se muestra una vez)

### 2. Pegar en el .env
```
GITHUB_CLIENT_ID=Ov23li...
GITHUB_CLIENT_SECRET=...
```

---

## ✅ Probar

1. Reinicia el server: `run-dev.bat`
2. Abre http://localhost:8000/auth/google → te debe redirigir a Google
3. Logueate → te redirige de vuelta y ves "✓ AUTENTICADO"
4. Igual con http://localhost:8000/auth/github

## 🚀 En producción (cuando subamos a Railway)

Tendrás que volver a:
1. Google Cloud → Credenciales → editar la credencial → agregar la URL nueva de Railway en redirect URIs
2. GitHub → Settings → Developer settings → tu OAuth App → cambiar callback URL

Esos cambios los hacemos en la sesión 5 (cuando despleguemos).
