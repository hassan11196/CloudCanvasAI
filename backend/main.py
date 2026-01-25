from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import chat, files

app = FastAPI(
    title="Zephior API",
    description="Backend API for Zephior",
    version="0.1.0"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(chat.router)
app.include_router(files.router)


@app.get("/")
async def root():
    return {"message": "Welcome to Zephior API"}


@app.get("/health")
async def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)