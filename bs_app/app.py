import os
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

app = FastAPI()

BASE_DIR = os.path.dirname(__file__)
INDEX_PATH = os.path.join(BASE_DIR, "templates", "index.html")

# Utility functions

def parse_matrix(text: str):
    lines = text.strip().splitlines()
    matrix = []
    for line in lines:
        row = [float(x) for x in line.split(',')]
        matrix.append(row)
    return matrix

def multiply_vector_matrix(vector, matrix):
    result = []
    for j in range(len(matrix[0])):
        s = 0.0
        for i in range(len(vector)):
            s += vector[i] * matrix[i][j]
        result.append(s)
    return result

def steady_state(matrix, tolerance=1e-6, max_iter=1000):
    # simple power iteration
    n = len(matrix)
    prob = [1.0 / n] * n
    for _ in range(max_iter):
        new_prob = multiply_vector_matrix(prob, matrix)
        diff = sum(abs(a - b) for a, b in zip(prob, new_prob))
        prob = new_prob
        if diff < tolerance:
            break
    return prob

def monte_carlo(trials: int, steps: int):
    import random

    up_prob = []
    for _ in range(trials):
        state = 0  # 0: up, 1: down waiting, 2: repair
        up_time = 0
        for _ in range(steps):
            r = random.random()
            if state == 0:
                state = 0 if r < 0.98 else 1
            elif state == 1:
                state = 2
            else:  # state==2
                state = 0 if r < 0.95 else 2
            if state == 0:
                up_time += 1
        up_prob.append(up_time / steps)
    return sum(up_prob) / trials

@app.get("/", response_class=HTMLResponse)
def read_index():
    with open(INDEX_PATH, "r", encoding="utf-8") as f:
        return f.read()

@app.get("/markov", response_class=HTMLResponse)
def markov(matrix: str):
    m = parse_matrix(matrix)
    probs = steady_state(m)
    availability = probs[0]
    html = f"<h2>Markov结果</h2><p>稳态概率: {probs}</p><p>系统可用度: {availability:.4f}</p><a href='/'>&larr; 返回</a>"
    return html

@app.get("/montecarlo", response_class=HTMLResponse)
def monte_carlo_route(trials: int, steps: int):
    availability = monte_carlo(trials, steps)
    html = f"<h2>蒙特卡罗仿真结果</h2><p>平均可用度: {availability:.4f}</p><a href='/'>&larr; 返回</a>"
    return html

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8001)

