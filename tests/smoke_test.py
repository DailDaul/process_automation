from app import create_app
app=create_app({'TESTING':True,'DATABASE_URL':'sqlite:///:memory:','SECRET_KEY':'test'})
client=app.test_client()
assert client.get('/').status_code==200
assert client.get('/health').json['status']=='ok'
assert client.get('/catalog/').status_code==200
assert client.get('/auth/login').status_code==200
print('Smoke tests passed')
