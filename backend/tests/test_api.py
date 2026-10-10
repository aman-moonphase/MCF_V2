import pytest
import uuid
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_health_check(authenticated_client: AsyncClient):
    response = await authenticated_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

@pytest.mark.asyncio
async def test_db_health_check(authenticated_client: AsyncClient):
    response = await authenticated_client.get("/health/db")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

@pytest.mark.asyncio
async def test_create_and_read_project(authenticated_client: AsyncClient):
    project_data = {
        "title": "Test Project",
        "description": "Test Desc",
        "source_type": "URL",
        "source_reference": "http://example.com"
    }
    
    response = await authenticated_client.post("/api/projects", json=project_data)
    assert response.status_code == 201
    created_project = response.json()
    assert created_project["title"] == "Test Project"
    
    project_id = created_project["id"]
    
    # Read back
    response = await authenticated_client.get(f"/api/projects/{project_id}")
    assert response.status_code == 200
    assert response.json()["id"] == project_id

@pytest.mark.asyncio
async def test_list_projects(authenticated_client: AsyncClient):
    # Ensure there's at least one project
    project_data = {
        "title": "List Project",
        "source_type": "TEXT",
        "source_reference": "None"
    }
    await authenticated_client.post("/api/projects", json=project_data)
    
    response = await authenticated_client.get("/api/projects")
    assert response.status_code == 200
    projects = response.json()
    assert isinstance(projects, list)
    assert len(projects) >= 1

@pytest.mark.asyncio
async def test_update_project(authenticated_client: AsyncClient):
    project_data = {
        "title": "Old Title",
        "source_type": "TEXT",
        "source_reference": "None"
    }
    res = await authenticated_client.post("/api/projects", json=project_data)
    project_id = res.json()["id"]
    
    update_data = {"title": "New Title"}
    update_res = await authenticated_client.patch(f"/api/projects/{project_id}", json=update_data)
    assert update_res.status_code == 200
    assert update_res.json()["title"] == "New Title"

@pytest.mark.asyncio
async def test_delete_project(authenticated_client: AsyncClient):
    project_data = {
        "title": "To be deleted",
        "source_type": "TEXT",
        "source_reference": "None"
    }
    res = await authenticated_client.post("/api/projects", json=project_data)
    project_id = res.json()["id"]
    
    delete_res = await authenticated_client.delete(f"/api/projects/{project_id}")
    assert delete_res.status_code == 204
    
    # Verify it's deleted (assuming a 404 is returned)
    read_res = await authenticated_client.get(f"/api/projects/{project_id}")
    assert read_res.status_code == 404

@pytest.mark.asyncio
async def test_invalid_project_id(authenticated_client: AsyncClient):
    fake_id = str(uuid.uuid4())
    response = await authenticated_client.get(f"/api/projects/{fake_id}")
    assert response.status_code == 404

@pytest.mark.asyncio
async def test_create_and_read_stage(authenticated_client: AsyncClient):
    project_data = {
        "title": "Stage Project",
        "source_type": "URL",
        "source_reference": "http://example.com"
    }
    
    p_res = await authenticated_client.post("/api/projects", json=project_data)
    project_id = p_res.json()["id"]
    
    stage_data = {
        "stage_type": "content-type",
        "status": "In Progress",
        "data": {"key": "value"}
    }
    
    # Create / Update stage
    s_res = await authenticated_client.put(f"/api/projects/{project_id}/stages/content-type", json=stage_data)
    assert s_res.status_code == 200
    assert s_res.json()["status"] == "In Progress"
    
    # Read single stage
    read_s_res = await authenticated_client.get(f"/api/projects/{project_id}/stages/content-type")
    assert read_s_res.status_code == 200
    assert read_s_res.json()["stage_type"] == "content-type"

    # Read all stages
    read_all_s_res = await authenticated_client.get(f"/api/projects/{project_id}/stages")
    assert read_all_s_res.status_code == 200
    stages = read_all_s_res.json()
    assert isinstance(stages, list)
    assert len(stages) >= 1
    assert any(s["stage_type"] == "content-type" for s in stages)

@pytest.mark.asyncio
async def test_invalid_stage(authenticated_client: AsyncClient):
    project_data = {
        "title": "Invalid Stage Project",
        "source_type": "TEXT",
        "source_reference": "None"
    }
    p_res = await authenticated_client.post("/api/projects", json=project_data)
    project_id = p_res.json()["id"]
    
    # Stage that doesn't exist
    response = await authenticated_client.get(f"/api/projects/{project_id}/stages/invalid-stage-name")
    assert response.status_code == 404
@pytest.mark.asyncio
async def test_cross_user_isolation(authenticated_client: AsyncClient, db_session, test_user):
    # User 1 (test_user) creates a project
    project_data = {
        "title": "User 1 Project",
        "source_type": "TEXT",
        "source_reference": "None"
    }
    p_res = await authenticated_client.post("/api/projects", json=project_data)
    assert p_res.status_code == 201
    project_id = p_res.json()["id"]

    # Create User 2
    from app.models.user import User
    from app.core.security import get_password_hash, create_access_token
    from datetime import timedelta
    from app.core.config import settings
    
    user2 = User(
        email="user2@example.com",
        hashed_password=get_password_hash("testpassword2"),
        is_active=True
    )
    db_session.add(user2)
    await db_session.commit()
    await db_session.refresh(user2)
    
    # Authenticate User 2
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        subject=str(user2.id), expires_delta=access_token_expires
    )
    
    # User 2 tries to access User 1's project
    headers = {"Authorization": f"Bearer {access_token}"}
    from httpx import AsyncClient as HttpxAsyncClient, ASGITransport
    from app.main import app
    async with HttpxAsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac2:
        ac2.headers.update(headers)
        
        # Test GET
        res = await ac2.get(f"/api/projects/{project_id}")
        assert res.status_code == 404
        
        # Test PUT
        res = await ac2.patch(f"/api/projects/{project_id}", json={"title": "Hacked"})
        assert res.status_code == 404
        
        # Test DELETE
        res = await ac2.delete(f"/api/projects/{project_id}")
        assert res.status_code == 404

        # Test listing
        res = await ac2.get("/api/projects")
        assert res.status_code == 200
        assert len(res.json()) == 0

@pytest.mark.asyncio
async def test_delete_project(authenticated_client: AsyncClient, db_session):
    # 1. Create a project
    project_data = {
        "title": "Project to Delete",
        "description": "Will be deleted",
        "source_type": "URL",
        "source_reference": "http://example.com/delete"
    }
    
    response = await authenticated_client.post("/api/projects", json=project_data)
    assert response.status_code == 201
    created_project = response.json()
    project_id = created_project["id"]
    
    # 2. Verify it exists
    response = await authenticated_client.get(f"/api/projects/{project_id}")
    assert response.status_code == 200
    
    # 3. Delete it
    response = await authenticated_client.delete(f"/api/projects/{project_id}")
    assert response.status_code == 204
    
    # 4. Verify it's gone
    response = await authenticated_client.get(f"/api/projects/{project_id}")
    assert response.status_code == 404

@pytest.mark.asyncio
async def test_delete_nonexistent_project(authenticated_client: AsyncClient):
    fake_id = str(uuid.uuid4())
    response = await authenticated_client.delete(f"/api/projects/{fake_id}")
    assert response.status_code == 404
