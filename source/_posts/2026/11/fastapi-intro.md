---
title: FastAPI 入门到进阶
date: 2026-11-06 12:00:00
description: 面向新手的 FastAPI 教程：从一个能跑的最小服务开始，一步一步加参数、请求体、依赖注入、数据库、鉴权、测试和部署，每加一个功能都能立刻跑通。不堆术语，先把心智模型讲清楚。
categories:
  - 技术
tags:
  - Python
  - FastAPI
  - 后端
  - Web 框架
cover: /img/2026/11/cover-fastapi-py.jpg
---

## 1. 先说人话：FastAPI 到底帮你省了什么

写后端接口，你其实一直在重复做三件事：**解析请求、校验数据、写文档**。FastAPI 的核心理念就是——**你只写一次 Python 类型注解，这三件事它全包了**。

举个最小例子。你声明一个函数：

```python
@app.get("/items/{item_id}")
def read_item(item_id: int, q: str | None = None):
    ...
```

FastAPI 看到 `item_id: int`，会自动：从 URL 路径拿到 `item_id`、把它转成整数、转不动就返回 422 错误；看到返回类型，自动生成 OpenAPI 文档和 Swagger UI（`/docs`），你不用写一行 yaml。

对比一下不同框架做同一件事的差别：

| 框架 | 校验怎么来 | 文档怎么来 | 适合谁 |
| --- | --- | --- | --- |
| Flask | 自己写 `if not isinstance(...)` | 装扩展、手写 | 想完全自己控制 |
| Django REST | 写 Serializer | 装 drf-spectacular | 要 Admin/ORM 全家桶的中后台 |
| **FastAPI** | **写个 Pydantic 模型** | **自动生成** | 想要类型安全 + 文档 + 异步的 API 服务 |

一句话：**要"类型安全 + 自动文档 + 异步"的 API，选 FastAPI；要 Admin/ORM 全家桶，Django 更省事。**

几个前提名词（后面会反复用到，先有个印象即可）：

- **ASGI**：异步服务器网关接口，让你的应用能跑 `async def`，并发更高。
- **Pydantic**：专门做"数据校验和类型转换"的库，FastAPI 的校验全靠它。
- **类型注解**：`item_id: int` 这种写法，Python 3.5+ 支持，FastAPI 靠它理解你的意图。

环境要求：**Python ≥ 3.10**。

## 2. 第一步：5 分钟跑起来

装包（用 `uv` 或 `pip` 都行，本文用 `pip`）：

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install "fastapi[standard]"
```

`[standard]` 不是可选糖，它装了上线要用的全套：`uvicorn`（服务器）、`python-multipart`（表单）、`httpx`（测试）、`pydantic-settings`（配置）等。

新建 `main.py`，先写能跑的最小服务：

```python
# main.py
from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def hello():
    return {"msg": "hello, fastapi"}
```

启动：

```bash
fastapi dev main.py
```

打开 http://127.0.0.1:8000 —— 看到 `{"msg":"hello, fastapi"}`。再打开 http://127.0.0.1:8000/docs —— 一个能直接点"Try it out"发请求的界面，**这就是自动文档**，你一行没写。

> `fastapi dev` 是开发模式：只监听本机（127.0.0.1）、改代码自动重启。上线用 `fastapi run main.py`（监听 0.0.0.0、不重启），后面部署章节再讲。

## 3. 第二步：接收参数

接口大多要接收输入。FastAPI 用**类型注解**判断参数从哪来：

| 你写的 | 参数来自 |
| --- | --- |
| `item_id: int`（出现在路径 `/items/{item_id}` 里） | 路径 |
| `q: str = None`（普通类型、不在路径里） | 查询参数（URL `?q=...`） |
| `item: Item`（Pydantic 模型） | 请求体 JSON |
| `Annotated[X, Query()/Header()/Form()]` | 显式指定来源 |

写个同时有路径参数和查询参数的接口：

```python
from typing import Annotated
from fastapi import FastAPI, Path, Query

app = FastAPI()

@app.get("/items/{item_id}")
def read_item(
    item_id: Annotated[int, Path()],          # 来自路径，必须是整数
    q: Annotated[str | None, Query(max_length=50)] = None,  # 来自 ?q=，可选
):
    return {"item_id": item_id, "q": q}
```

两个关键点：

1. **类型注解不能省**。写成 `item_id: int` 和写成 `item_id`（无注解）完全不同——后者 FastAPI 不知道它该是路径还是查询，会当成查询参数，路径模板里的 `{item_id}` 就接不到了。
2. **校验内嵌在注解里**。`Query(max_length=50)` 表示查询参数 `q` 最多 50 字符，超了自动 422。访问 `/items/3?q=hi` 返回 `{"item_id":3,"q":"hi"}`；访问 `/items/abc` 直接 422（因为 `abc` 不是整数）。

`Path()`、`Query()` 还能加 `ge`/`le`（数值范围）、`pattern`（正则）等约束，需要时查文档即可。

## 4. 第三步：请求体，用 Pydantic 模型

要接收 JSON 请求体（比如创建一个资源），写一个 Pydantic 模型，把它当参数类型：

```python
from pydantic import BaseModel

class Item(BaseModel):
    name: str
    price: float

@app.post("/items/")
def create_item(item: Item):
    return item
```

`POST /items/` 发送 `{"name":"键盘","price":299}`，FastAPI 自动解析成 `Item` 对象、校验两个字段类型、缺失或类型错就 422。

**关键习惯：输入模型和输出模型分开写**。原因——你不想把密码、内部字段通过返回值漏出去。FastAPI 用 `response_model` 过滤返回值：

```python
class ItemIn(BaseModel):
    name: str
    price: float

class ItemOut(BaseModel):
    id: int
    name: str
    # 注意：没有 price 字段

@app.post("/items/", response_model=ItemOut)
def create_item(item: ItemIn):
    # 这里多返回一个 price，但 response_model 会把它裁掉
    return {"id": 1, "name": item.name, "price": item.price}

# 实际返回 {"id":1,"name":"键盘"} —— price 被过滤了
```

`response_model` 是真的会裁字段，不是文档提示。所以"输入能写什么"和"输出露出什么"可以在两个模型里分别控制。

## 5. 第四步：复用逻辑，用依赖注入

很多接口都要做同一件事：校验登录 token、拿数据库连接。与其每个函数复制粘贴，不如抽成**依赖（Depends）**，让 FastAPI 负责调用和传递。

最简单的用法——只做校验，不返回东西，挂在一组路由上：

```python
from fastapi import Depends, FastAPI, Header, HTTPException, status

app = FastAPI()

def check_token(x_token: Annotated[str, Header()]):
    if x_token != "secret":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad token")

# 这条路由要求请求头带 X-Token: secret
@app.get("/me", dependencies=[Depends(check_token)])
def me():
    return {"user": "alice"}
```

要**把依赖的结果传给路由**，就写在函数参数里：

```python
def get_current_user(x_token: Annotated[str, Header()]):
    if x_token != "secret":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad token")
    return "alice"          # 这个返回值会传给路由

@app.get("/me")
def me(user: Annotated[str, Depends(get_current_user)]):
    return {"user": user}   # user == "alice"
```

需要**用完要还回去**的资源（数据库会话、文件句柄），用 `yield` 写法：

```python
from typing import Annotated, AsyncIterator
from fastapi import Depends

async def get_db() -> AsyncIterator["Session"]:
    async with SessionLocal() as session:
        yield session        # 路由用完，这里自动回收
```

`yield` 之前的代码在请求进来前执行，之后的代码在响应发完后执行——资源一定会被释放，不会出现"忘了关连接"。

## 6. 第五步：接上数据库

下面给一个**最小可运行的待办事项 API**：用 SQLAlchemy（异步版）存数据。先把前面几步串起来，这段代码可以直接 `fastapi dev main.py` 跑通。

```python
from contextlib import asynccontextmanager
from typing import Annotated, AsyncIterator
from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# 1) 定义表
class Base(DeclarativeBase): pass

class Todo(Base):
    __tablename__ = "todo"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str]
    done: Mapped[bool] = mapped_column(default=False)

# 2) 建引擎和会话工厂（这里用内存数据库，重启即清空，方便演示）
engine = create_async_engine("sqlite+aiosqlite:///:memory:")
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

# 3) 启动/关闭：建表、释放连接
@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()

app = FastAPI(lifespan=lifespan)

# 4) 数据库依赖
async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session

# 5) 极简鉴权
def get_current_user(x_token: Annotated[str, Header()]):
    if x_token != "secret":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad token")
    return "alice"

# 6) 请求/响应模型
class TodoCreate(BaseModel):
    title: str

class TodoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)   # 允许直接吃 ORM 对象
    id: int
    title: str
    done: bool

# 7) 路由
@app.get("/todos", response_model=list[TodoOut])
async def list_todos(db: Annotated[AsyncSession, Depends(get_db)]):
    res = await db.execute(select(Todo))
    return list(res.scalars())

@app.post("/todos", response_model=TodoOut, status_code=201)
async def create_todo(
    t: TodoCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[str, Depends(get_current_user)],
):
    todo = Todo(title=t.title)
    db.add(todo)
    await db.commit()
    await db.refresh(todo)   # 拿回自增 id
    return todo              # from_attributes 让它能被 TodoOut 序列化

@app.get("/me", response_model=dict)
def me(user: Annotated[str, Depends(get_current_user)]):
    return {"user": user}
```

几个新手容易懵的点：

- `expire_on_commit=False`：不加的话，`commit` 后对象属性会失效，序列化时触发惰性加载报错。
- `from_attributes=True`：让 `TodoOut` 能直接吃 ORM 对象（而不是 dict）。
- `await db.refresh(todo)`：数据库生成的自增 `id` 要刷回对象才能返回。
- 生产把 `sqlite+aiosqlite:///:memory:` 换成真正的库（如 `postgresql+asyncpg://...`）。

## 7. 第六步：写测试

FastAPI 自带 `TestClient`，不用起真服务器就能测：

```python
from fastapi.testclient import TestClient
from main import app

# 用 with 进入，才会触发 lifespan（建表）
with TestClient(app) as c:
    r = c.post("/todos", json={"title": "写教程"}, headers={"x-token": "secret"})
    assert r.status_code == 201
    assert r.json()["title"] == "写教程"

    r = c.get("/todos", headers={"x-token": "secret"})
    assert r.status_code == 200
    assert len(r.json()) == 1

    # 没带 / 带错 token 都会被拦下
    assert c.get("/me").status_code == 422          # 缺必需头
    assert c.get("/me", headers={"x-token": "wrong"}).status_code == 401
```

异步接口用 `httpx.AsyncClient` 配 `ASGITransport`，需要 `pip install pytest pytest-asyncio`。

## 8. 第七步：部署上线

本地 `fastapi dev` 只能本机访问。上线用 `fastapi run`（监听 0.0.0.0、不自动重启），多进程就加 `--workers`：

```bash
fastapi run main.py --host 0.0.0.0 --port 8000 --workers 4
# 等价于：uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
```

容器化（多进程用 workers，不用再装 gunicorn）：

```dockerfile
FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["fastapi", "run", "main.py", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
```

```text
# requirements.txt
fastapi[standard]==0.162.0
aiosqlite
sqlalchemy[asyncio]
```

要点：

- **版本要 pin**（写死 `==0.162.0`）。FastAPI 还是 `0.x`，小版本号升级就可能破坏兼容。
- 容器里必须 `--host 0.0.0.0`，否则只有容器内部能访问。
- HTTPS 交给前面的 Nginx / 云负载均衡处理，别在应用里自己搞。
- 生产环境记得关掉 `/docs`（设 `docs_url=None`），别把接口文档裸露在外。

## 9. 新手最常踩的坑

- **路径参数忘了写类型**：`def f(id):` 不会去接 `/items/{id}`，必须 `id: int` 这种带注解。
- **路由顺序**：`@app.get("/items/me")` 要写在 `@app.get("/items/{item_id}")` **之前**，否则 `me` 会被 `{item_id}` 吃掉。判断不出就直接用不同路径，最省心。
- **`async def` 里做阻塞调用**：`requests.get()`、`time.sleep()` 会卡住整个事件循环。有 `await` 的库就 `async def`，没有就用 `def`（FastAPI 会把 `def` 丢进线程池）。
- **`response_model` 会裁字段**：想多返回内部字段，是模型没写进去，不是 bug。
- **表单和 JSON 不能混**：一旦某参数用了 `Form()`，整个请求就变成表单编码，再声明 `Body` 字段会 422。
- **必填的布尔表单字段**：FastAPI 0.162 起，HTML 复选框没传就 422（以前会偷偷填 `False`）。要默认值就写 `Annotated[bool, Form()] = False`。
- **少依赖头 vs 少鉴权头**：缺 `Header()` 必需头返回 422，缺 `HTTPBearer`/`OAuth2PasswordBearer` 的 token 返回 401——不是同一个概念。

## 10. 下一步看什么

到这一行，你已经能写出一个带校验、数据库、鉴权、测试的 FastAPI 服务了。想继续深入：

- **更复杂的依赖**：`yield` 依赖的 `scope`（提前释放资源）、子依赖、测试时用 `app.dependency_overrides` 替换外部依赖。
- **可观测性**：FastAPI 0.142 起内置 OpenTelemetry，配几个环境变量就能把请求链路发到 OTel 后端。
- **工程化**：`APIRouter` 拆分路由、`pydantic-settings` 管配置、分层目录结构。

## 11. 参考

- [FastAPI 官方文档](https://fastapi.tiangolo.com/)
- [FastAPI 发布说明（release notes）](https://fastapi.tiangolo.com/release-notes/)
- [FastAPI CLI（dev / run）](https://fastapi.tiangolo.com/fastapi-cli/)
- [Pydantic 官方文档](https://docs.pydantic.dev/)
- [SQLAlchemy 2.0 异步文档](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)
- [Starlette 并发（async / await）](https://starlette.dev/async/)
</content>
</write>
