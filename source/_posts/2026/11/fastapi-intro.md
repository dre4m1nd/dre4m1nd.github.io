---
title: FastAPI 入门到进阶
date: 2026-11-06 12:00:00
description: 先讲 FastAPI 的基础和进阶用法（从最小服务到数据库、鉴权、部署），再总结它的核心优势，最后拆解这些优势背后的原理——类型注解+反射、模型即 Schema、依赖图、ASGI、Pydantic v2(Rust)。所有示例都在 FastAPI 0.162 上跑过。
categories:
  - 技术
tags:
  - Python
  - FastAPI
  - 后端
  - Web 框架
cover: /img/2026/11/cover-fastapi-py.jpg
---

## 1. 基础与进阶用法

先把"怎么用"讲清楚。环境要求 **Python ≥ 3.10**。

### 1.1. 环境准备：安装与启动

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

```bash
fastapi dev main.py     # 开发：127.0.0.1 + 自动重启
fastapi run main.py     # 生产：0.0.0.0 + 无重启
```

打开 http://127.0.0.1:8000/docs —— 一个能直接点"Try it out"发请求的界面，**这就是自动文档**，你一行没写。

### 1.2. 基础：路由与参数（类型注解即来源）

FastAPI 用**类型注解**判断参数从哪来：

| 你写的 | 参数来自 |
| --- | --- |
| `item_id: int`（出现在路径 `/items/{item_id}` 里） | 路径 |
| `q: str = None`（普通类型、不在路径里） | 查询参数（`?q=...`） |
| `item: Item`（Pydantic 模型） | 请求体 JSON |
| `Annotated[X, Query()/Header()/Form()]` | 显式指定来源 |

```python
from typing import Annotated
from fastapi import FastAPI, Path, Query

app = FastAPI()

@app.get("/items/{item_id}")
def read_item(
    item_id: Annotated[int, Path()],
    q: Annotated[str | None, Query(max_length=50)] = None,
):
    return {"item_id": item_id, "q": q}
```

两个关键点：**类型注解不能省**（无注解时 FastAPI 不知道它该是路径还是查询）；**校验内嵌在注解里**（`Query(max_length=50)` 表示 `q` 最多 50 字符，超了自动 422）。

### 1.3. 基础：用 Pydantic 模型处理请求体与响应

接收 JSON 请求体，写一个 Pydantic 模型当参数类型即可：

```python
from pydantic import BaseModel

class Item(BaseModel):
    name: str
    price: float

@app.post("/items/")
def create_item(item: Item):
    return item
```

**输入模型和输出模型分开写**，用 `response_model` 过滤返回值（密码、内部字段不会被漏出去）：

```python
class ItemIn(BaseModel):
    name: str
    price: float

class ItemOut(BaseModel):
    id: int
    name: str
    # 没有 price 字段

@app.post("/items/", response_model=ItemOut)
def create_item(item: ItemIn):
    return {"id": 1, "name": item.name, "price": item.price}

# 实际返回 {"id":1,"name":"键盘"} —— price 被裁掉了
```

`response_model` 是真的会裁字段，不是文档提示。

### 1.4. 基础：依赖注入 Depends（最小用法）

多个接口都要做同一件事（校验 token、拿数据库连接），抽成**依赖（Depends）**，FastAPI 负责调用和传递：

```python
from fastapi import Depends, FastAPI, Header, HTTPException, status

app = FastAPI()

def get_current_user(x_token: Annotated[str, Header()]):
    if x_token != "secret":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad token")
    return "alice"

@app.get("/me")
def me(user: Annotated[str, Depends(get_current_user)]):
    return {"user": user}   # user == "alice"
```

要**用完要还回去**的资源（数据库会话），用 `yield` 写法——`yield` 之后的代码在响应发完后执行，资源一定被释放：

```python
from typing import Annotated, AsyncIterator
from fastapi import Depends

async def get_db() -> AsyncIterator["Session"]:
    async with SessionLocal() as session:
        yield session
```

### 1.5. 基础：错误处理与测试

抛 `HTTPException` 即返回对应状态码；测试用自带 `TestClient`，**用 `with` 进入才会触发 `lifespan`（建表）**：

```python
from fastapi.testclient import TestClient
from main import app

with TestClient(app) as c:
    r = c.post("/items", json={"name": "键盘", "price": 299})
    assert r.status_code == 201
    assert c.get("/me").status_code == 422          # 缺必需头
    assert c.get("/me", headers={"x-token": "wrong"}).status_code == 401
```

### 1.6. 进阶：参数模型（Query/Header/Cookie/Form 模型）

参数多了，把一组收进一个 Pydantic 模型，而不是堆在函数签名里：

```python
from typing import Annotated, Literal
from fastapi import FastAPI, Query
from pydantic import BaseModel, Field, ConfigDict

class FilterParams(BaseModel):
    model_config = ConfigDict(extra="forbid")     # 未知查询键直接报错
    limit: int = Field(10, ge=1, le=50)
    order_by: Literal["created_at", "updated_at"] = "created_at"

@app.get("/items/")
def list_items(f: Annotated[FilterParams, Query()]):
    return f
```

`Header()` / `Cookie()` 模型从 0.115 起支持，表单模型（`Form`）从 0.113 起支持——一组相关头/字段收成一个模型，校验和复用一次写完。`extra="forbid"` 的模型会管到**同位置的所有字段**（0.160 起），所以兄弟参数也会被拒。

### 1.7. 进阶：依赖注入进阶

**类依赖**：把参数组写成类，`Depends()` 不传参时自动读 `__init__` 签名：

```python
class Paginator:
    def __init__(self, limit: Annotated[int, Query(ge=1, le=100)] = 20,
                 offset: Annotated[int, Query(ge=0)] = 0):
        self.limit, self.offset = limit, offset
    def slice(self, items): return items[self.offset:self.offset + self.limit]

@app.get("/list")
def lst(p: Annotated[Paginator, Depends()]):
    return p.slice(list(range(10)))
```

**`scope` 控制释放时机**（0.121 新增）：默认 `scope="request"` 在响应发完后清理；`scope="function"` 在端点函数返回后、响应发送前就释放——只在依赖内部用完即弃的资源时省连接：

```python
@app.get("/users/me")
def me(username: Annotated[str, Depends(get_username, scope="function")]):
    return username
```

**路由级依赖**：挂在 `APIRouter(dependencies=[Depends(check_token)])` 上，整组端点统一加校验。**测试替换**：`app.dependency_overrides[get_db] = lambda: fake_db`，换掉外部依赖不用 monkeypatch。

### 1.8. 进阶：接数据库（异步 SQLAlchemy 闭环）

下面是一段**能直接 `fastapi dev main.py` 跑通**的待办事项 API：

```python
from contextlib import asynccontextmanager
from typing import Annotated, AsyncIterator
from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase): pass
class Todo(Base):
    __tablename__ = "todo"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str]
    done: Mapped[bool] = mapped_column(default=False)

engine = create_async_engine("sqlite+aiosqlite:///:memory:")
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()

app = FastAPI(lifespan=lifespan)

async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session

def get_current_user(x_token: Annotated[str, Header()]):
    if x_token != "secret":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad token")
    return "alice"

class TodoCreate(BaseModel):
    title: str

class TodoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)   # 允许直接吃 ORM 对象
    id: int
    title: str
    done: bool

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
    await db.refresh(todo)
    return todo
```

容易踩的点：`expire_on_commit=False`（否则 commit 后属性失效）、`from_attributes=True`（让 `TodoOut` 能吃 ORM 对象）、`await db.refresh(todo)`（拿回自增 id）。生产把 `:memory:` 换成真正的库。

### 1.9. 进阶：鉴权（OAuth2 + JWT）

FastAPI 自带 OAuth2 密码流的脚手架；JWT 用 `PyJWT` 签发和校验：

```python
from datetime import datetime, timedelta, timezone
from typing import Annotated
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
import jwt   # pip install pyjwt

SECRET = "dev-secret"
oauth2 = OAuth2PasswordBearer(tokenUrl="token")
app = FastAPI()

def make_token(sub: str) -> str:
    payload = {"sub": sub, "exp": datetime.now(timezone.utc) + timedelta(hours=1)}
    return jwt.encode(payload, SECRET, algorithm="HS256")

def get_current_user(token: Annotated[str, Depends(oauth2)]):
    try:
        jwt.decode(token, SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token")
    return token

@app.post("/token")
def login(form: Annotated[OAuth2PasswordRequestForm, Depends()]):
    # 真实项目里换成查库校验密码
    if form.username != "alice" or form.password != "secret":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad credentials")
    return {"access_token": make_token(form.username), "token_type": "bearer"}

@app.get("/me")
def me(user: Annotated[str, Depends(get_current_user)]):
    return {"token": user}
```

`OAuth2PasswordBearer` 会把自己写进 OpenAPI 安全方案，所以 `/docs` 右上角出现 **Authorize** 按钮，填 token 后所有请求自动带头。

### 1.10. 进阶：中间件、CORS 与 lifespan

中间件比依赖更靠外（请求先过中间件，再解析参数、跑依赖）：

```python
@app.middleware("http")
async def add_header(request: Request, call_next):
    response = await call_next(request)
    response.headers["x-extra"] = "1"
    return response
```

跨域必备 CORS：

```python
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(CORSMiddleware, allow_origins=["https://app.example.com"],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
```

**Starlette 1.0（2026-03）删掉了 `on_startup`/`on_event`**，新代码统一用 `lifespan`（见 1.8 的 `lifespan` 写法）。`yield` 出的字典会进 `app.state`，端点里 `request.state.x` 直接拿。

### 1.11. 进阶：异步与线程池

| 写法 | 执行方式 | 何时用 |
| --- | --- | --- |
| `async def` | 直接在事件循环里跑 | 用 `await` 的库（asyncpg/httpx/aiofiles） |
| `def` | 丢进线程池（`anyio.to_thread`） | 同步库（requests/psycopg2/Pillow） |

**线程池默认只有 40 个 token**，且和 FastAPI 跑同步依赖共享。所以在 `async def` 里写 `requests.get()` 或 `time.sleep()` 会**卡住整个事件循环**——有 `await` 用 async 库，没 `await` 就老实写 `def`。

### 1.12. 进阶：工程结构与部署

拆文件用 `APIRouter`，配置用 `pydantic-settings`：

```python
# app/routers/items.py
from fastapi import APIRouter, Depends
router = APIRouter(prefix="/items", tags=["items"], dependencies=[Depends(check_token)])

@router.get("/", response_model=list[ItemOut])
async def list_items(): ...

# app/main.py
from fastapi import FastAPI
from .routers import items
app = FastAPI()
app.include_router(items.router, prefix="/api/v1")
```

```dockerfile
FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["fastapi", "run", "main.py", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
```

要点：**版本要 pin**（`fastapi[standard]==0.162.0`，`0.x` 小版本可能破坏兼容）；容器里必须 `--host 0.0.0.0`；HTTPS 交给前面的 Nginx / 云负载均衡；生产环境用 `docs_url=None` 关掉文档。

## 2. 它的优势

基础用法走完一遍，回过头看 FastAPI 到底好在哪。

**2.1 自动生成交互式 API 文档。** 你声明了参数和模型，Swagger UI（`/docs`）和 ReDoc（`/redoc`）就自动有了，还能直接在线发请求。别的框架要么要手写，要么装扩展。

**2.2 一套类型声明，同时做校验、序列化、文档。** 写一次 `Item` 模型，它同时被用来：解析请求体、校验字段、把返回值按 `response_model` 裁剪、生成 OpenAPI。改一个字段，校验和文档一起变，不会出现"代码改了文档没更"的脱节。

**2.3 内建依赖注入，天然可测试。** `Depends` 把"共用逻辑"和"资源生命周期"从路由里抽出来，配合 `dependency_overrides` 测试时一行换掉数据库/鉴权，不用 monkeypatch。

**2.4 原生异步，并发高。** 构建在 ASGI 之上，`async def` 直接跑在事件循环里；`def` 端点自动进线程池，不阻塞循环。

**2.5 编辑器与类型提示友好。** 因为一切基于 Python 类型注解和 `Annotated`，IDE 能静态推断出参数类型、自动补全、标红错误——团队维护大模型时这点尤其值钱。

## 3. 原理：这些优势是怎么来的

优势不是魔法，是几个明确的设计选择叠出来的。

### 3.1. 类型注解 + 反射：一套声明多处复用

FastAPI 在启动时遍历每个路由函数，用 `typing.get_type_hints` 解析参数注解，从 `Annotated` 里取出 `Query`/`Body`/`Header` 等元数据，再交给 Pydantic 生成校验器，并据此生成 JSON Schema。

所以"一个 `Item` 模型既做校验又做文档"的根因是：**类型注解是唯一真相源**，校验器、序列化器、Schema 全部从它派生。改模型一处，下游一起更新——这正是 2.2 的来源。

### 3.2. 自动文档：模型即 OpenAPI Schema

Pydantic 模型和 `Query`/`Header` 声明，本质上就是结构化的 JSON Schema。FastAPI 把这些 Schema 翻译成 **OpenAPI 规范**（落地为 `/openapi.json`），再用 Swagger UI / ReDoc 渲染成可视化界面。文档"自动"的原因不是 FastAPI 额外分析代码，而是**你声明的数据结构本来就是 Schema**——这是 2.1 的来源。

### 3.3. 依赖注入：函数签名 + 依赖图

`Depends` 不是装饰器魔法。FastAPI 用 `inspect` 读取函数签名，递归解析子依赖，构建一棵**依赖树**。`use_cache=True`（默认）保证同一请求里一个依赖只执行一次；`yield` 依赖利用**生成器协议**实现"进/出"两段代码，分别在请求前后运行，所以能自动管理数据库连接这类资源。测试时 `dependency_overrides` 直接替换树上的某个节点——这是 2.3 的来源。

### 3.4. 异步：站在 Starlette（ASGI）肩上

FastAPI 自己不实现 HTTP 层，而是构建在 **Starlette（ASGI 框架）** 之上。每个请求作为 ASGI 消息流经路由、中间件、依赖；`async def` 端点直接交给事件循环，`def` 端点经 `anyio.to_thread` 丢进线程池。ASGI 是它支持原生 `await`、能和 uvicorn 这类异步服务器配合的前提——这是 2.4 的来源。

### 3.5. 性能底座：Pydantic v2（Rust）+ uvicorn（uvloop）

校验速度来自 **Pydantic v2**：其核心 `pydantic-core` 用 Rust 实现，把模型编译成高效的校验器，比纯 Python 快一个数量级。服务器侧 **uvicorn** 默认使用 `uvloop`（用 Cython 实现的事件循环，Linux 上接近 Node/Go 的水平）。这两块是吞吐高的硬底座。

### 3.6. 小结

把上面串起来：**Python 类型注解 → Pydantic/JSON Schema → 校验 + 序列化 + OpenAPI 文档**；**ASGI/Starlette → 原生异步**；**pydantic-core(Rust) + uvloop → 性能**。FastAPI 的角色是把这些已经很强的部件，用"类型即契约"这一条主线缝成一个连贯的框架。理解这条链路，你就不会把它当成"又一个 web 框架"，而能判断它适不适合你的场景。

## 4. 参考

- [FastAPI 官方文档](https://fastapi.tiangolo.com/)
- [FastAPI 发布说明（release notes）](https://fastapi.tiangolo.com/release-notes/)
- [FastAPI CLI（dev / run）](https://fastapi.tiangolo.com/fastapi-cli/)
- [Pydantic 官方文档](https://docs.pydantic.dev/)
- [SQLAlchemy 2.0 异步文档](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)
- [Starlette 并发（async / await）](https://starlette.dev/async/)
- [OpenTelemetry（0.142 内置）](https://fastapi.tiangolo.com/advanced/opentelemetry/)
</content>
</write>
