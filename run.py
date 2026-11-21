from backend.app import app, E

if __name__ == "__main__":
    app.run(debug=E("FLASK_DEBUG") == "1", port=int(E("PORT", "5000")))
