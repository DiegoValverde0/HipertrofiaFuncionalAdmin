#!/usr/bin/env python
"""Script para hacer QA del endpoint /preview-dates y funcionalidad de membresías."""

import requests
import json
from datetime import datetime, date, timedelta

BASE_URL = "http://localhost:5000"

def create_session():
    """Crear una sesión autenticada"""
    session = requests.Session()
    
    # Intentar login con credenciales por defecto (admin/admin)
    login_url = f"{BASE_URL}/auth/login"
    credentials = {
        'correo': 'admin@gymadmin.local',
        'contrasena': 'admin'
    }
    
    print("\nIntentando autenticación...")
    response = session.post(login_url, data=credentials)
    
    if response.status_code == 200:
        print("✓ Autenticación exitosa")
        return session
    else:
        print(f"✗ Autenticación fallida: {response.status_code}")
        # Intentar encontrar un usuario válido
        print("  Nota: Si la autenticación falló, asegúrate de tener un usuario admin configurado")
        return None

def test_preview_endpoint(session):
    """Test del endpoint /preview-dates"""
    print("\n" + "="*60)
    print("TEST 1: Endpoint /preview-dates")
    print("="*60)
    
    # Test case 1: Nueva membresía (Mensual, comienza hoy)
    today_str = date.today().isoformat()
    params = {
        'fecha_inicio': today_str,
        'plan_id': 1,  # Asumiendo que existe el plan 1
        'opcion': 'new'
    }
    
    print(f"\n✓ Test 1.1: Nueva membresía (plan 1, comienza {today_str})")
    print(f"  URL: {BASE_URL}/membresias/preview-dates?fecha_inicio={today_str}&plan_id=1&opcion=new")
    response = session.get(f"{BASE_URL}/membresias/preview-dates", params=params)
    
    print(f"  Status Code: {response.status_code}")
    print(f"  Response Text: {response.text[:500]}")
    
    if response.status_code == 200:
        try:
            data = response.json()
            print(f"  Status: 200 OK")
            print(f"  Estado: {data.get('estado')}")
            print(f"  Fecha inicio: {data.get('fecha_inicio')}")
            print(f"  Fecha fin: {data.get('fecha_fin')}")
            print(f"  Días vigencia: {data.get('dias_vigencia')}")
            if data.get('estado') == 'valido':
                print("  ✓ PASS: Respuesta válida")
            else:
                print(f"  ✗ FAIL: Respuesta con estado {data.get('estado')}")
        except json.JSONDecodeError as e:
            print(f"  ✗ FAIL: Error al parsear JSON: {e}")
    else:
        print(f"  ✗ FAIL: Status {response.status_code}")
        print(f"  Response: {response.text}")
    
    # Test case 2: Fecha futura
    future_date = (date.today() + timedelta(days=30)).isoformat()
    params = {
        'fecha_inicio': future_date,
        'plan_id': 1,
        'opcion': 'new'
    }
    
    print(f"\n✓ Test 1.2: Membresía con fecha futura ({future_date})")
    response = requests.get(f"{BASE_URL}/membresias/preview-dates", params=params)
    
    if response.status_code == 200:
        data = response.json()
        print(f"  Status: 200 OK")
        print(f"  Estado: {data.get('estado')}")
        if data.get('estado') == 'valido':
            print("  ✓ PASS")
        else:
            print(f"  Estado: {data.get('estado')}, Msg: {data.get('mensaje')}")
    else:
        print(f"  ✗ FAIL: Status {response.status_code}")
    
    # Test case 3: Fecha pasada (más de 30 días)
    past_date = (date.today() - timedelta(days=60)).isoformat()
    params = {
        'fecha_inicio': past_date,
        'plan_id': 1,
        'opcion': 'new'
    }
    
    print(f"\n✓ Test 1.3: Membresía con fecha pasada (>30 días) ({past_date})")
    response = requests.get(f"{BASE_URL}/membresias/preview-dates", params=params)
    
    if response.status_code == 200:
        data = response.json()
        print(f"  Status: 200 OK")
        print(f"  Estado: {data.get('estado')}")
        if data.get('estado') == 'warning':
            print(f"  ✓ PASS: Genera warning como se espera")
            print(f"  Mensaje: {data.get('mensaje')}")
        else:
            print(f"  ✗ FAIL: Esperaba warning, obtuvo {data.get('estado')}")
    else:
        print(f"  ✗ FAIL: Status {response.status_code}")
    
    # Test case 4: Plan inexistente
    params = {
        'fecha_inicio': today_str,
        'plan_id': 99999,
        'opcion': 'new'
    }
    
    print(f"\n✓ Test 1.4: Plan inexistente (plan_id=99999)")
    response = requests.get(f"{BASE_URL}/membresias/preview-dates", params=params)
    
    if response.status_code == 200:
        data = response.json()
        print(f"  Status: 200 OK")
        print(f"  Estado: {data.get('estado')}")
        if data.get('estado') == 'error':
            print(f"  ✓ PASS: Genera error como se espera")
            print(f"  Mensaje: {data.get('mensaje')}")
        else:
            print(f"  ✗ FAIL: Esperaba error, obtuvo {data.get('estado')}")
    else:
        print(f"  ✗ FAIL: Status {response.status_code}")

def test_ajuste_fin_de_semana():
    """Test que fecha_fin se ajusta correctamente para fines de semana"""
    print("\n" + "="*60)
    print("TEST 2: Ajuste de fin de semana")
    print("="*60)
    
    # Buscar un sábado o domingo en los próximos 30 días
    test_date = date.today()
    for i in range(30):
        test_date = date.today() + timedelta(days=i)
        weekday = test_date.weekday()
        if weekday == 5:  # Saturday
            print(f"\n✓ Test 2.1: Membresía que termina en sábado ({test_date})")
            break
        elif weekday == 6:  # Sunday
            print(f"\n✓ Test 2.1: Membresía que termina en domingo ({test_date})")
            break
    
    params = {
        'fecha_inicio': test_date.isoformat(),
        'plan_id': 1,  # Plan mensual: +1 mes
        'opcion': 'new'
    }
    
    response = requests.get(f"{BASE_URL}/membresias/preview-dates", params=params)
    
    if response.status_code == 200:
        data = response.json()
        if data.get('estado') == 'valido':
            fecha_fin = datetime.fromisoformat(data.get('fecha_fin')).date()
            weekday_fin = fecha_fin.weekday()
            if weekday_fin not in [5, 6]:
                print(f"  Fecha fin: {fecha_fin}")
                print(f"  Día de semana: {['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo'][weekday_fin]}")
                print(f"  ✓ PASS: Fecha fin ajustada correctamente")
            else:
                print(f"  ✗ FAIL: Fecha fin es {['Sábado', 'Domingo'][weekday_fin-5]}")
        else:
            print(f"  ✗ FAIL: Estado {data.get('estado')}: {data.get('mensaje')}")
    else:
        print(f"  ✗ FAIL: Status {response.status_code}")

if __name__ == '__main__':
    print("\n" + "="*60)
    print("TESTING REFACTORIZACIÓN DE FECHAS EN MEMBRESÍAS")
    print("="*60)
    print(f"URL Base: {BASE_URL}")
    print(f"Fecha actual: {date.today()}")
    
    try:
        test_preview_endpoint()
        test_ajuste_fin_de_semana()
    except requests.exceptions.ConnectionError:
        print("\n✗ ERROR: No se pudo conectar al servidor en", BASE_URL)
        print("  Asegúrate de que Flask está corriendo en http://localhost:5000")
    except Exception as e:
        print(f"\n✗ ERROR: {e}")
    
    print("\n" + "="*60)
    print("FIN DE TESTS")
    print("="*60)
