"""
Architecture visualization router.

Returns the backend architecture as JSON for frontend graph rendering.
"""
from fastapi import APIRouter

from src.models.architecture import (
    ArchitectureNode,
    ArchitectureEdge,
    ArchitectureGroup,
    ArchitectureStats,
    ArchitectureMetadata,
    ArchitectureResponse,
)

router = APIRouter(tags=["Architecture"])


def _get_nodes() -> list[ArchitectureNode]:
    """Build all architecture nodes."""
    nodes = []

    # API Layer - Routers
    routers = [
        ("vacancies", "Vacancies", "Vacancy CRUD and listing"),
        ("applications", "Applications", "Application management"),
        ("candidates", "Candidates", "Candidate CRUD and timeline"),
        ("interviews", "Interviews", "Interview generation and feedback"),
        ("pre_screenings", "Pre-screenings", "Pre-screening configuration"),
        ("screening", "Screening", "Chat and simulation endpoints"),
        ("webhooks", "Webhooks", "Twilio and ElevenLabs webhooks"),
        ("vapi", "VAPI", "VAPI voice call events"),
        ("outbound", "Outbound", "Voice/WhatsApp screening initiation"),
        ("cv", "CV", "CV analysis via Gemini"),
        ("documents", "Documents", "Document verification"),
        ("document_collection", "Document Collection", "Document upload handling"),
        ("scheduling", "Scheduling", "Interview time slot management"),
        ("auth", "Auth", "OAuth login and token management"),
        ("workspaces", "Workspaces", "Workspace and team management"),
        ("data_query", "Data Query", "Natural language database queries"),
        ("demo", "Demo", "Demo data seeding"),
        ("health", "Health", "Health check endpoint"),
        ("monitoring", "Monitoring", "Global activity monitoring"),
        ("activities", "Activities", "Activity feed and workflows"),
        ("agents", "Agents", "Agent vacancy status"),
        ("elevenlabs", "ElevenLabs", "ElevenLabs agent configuration"),
        ("teams", "Teams", "Microsoft Teams webhook"),
    ]
    for id_suffix, name, desc in routers:
        nodes.append(ArchitectureNode(
            id=f"router:{id_suffix}",
            type="router",
            name=name,
            layer="api",
            file_path=f"src/routers/{id_suffix}.py",
            description=desc,
        ))

    # Service Layer
    services = [
        ("application", "ApplicationService", "src/services/application_service.py", "Application listing and creation"),
        ("vacancy", "VacancyService", "src/services/vacancy_service.py", "Vacancy business logic and stats"),
        ("pre_screening", "PreScreeningService", "src/services/pre_screening_service.py", "Pre-screening configuration"),
        ("interview", "InterviewService", "src/services/interview_service.py", "Interview generation streaming"),
        ("activity", "ActivityService", "src/services/activity_service.py", "Activity logging and timeline"),
        ("candidate_context", "CandidateContextService", "src/services/candidate_context_service.py", "Candidate context aggregation"),
        ("scheduling", "SchedulingService", "src/services/scheduling_service.py", "Interview scheduling"),
        ("auth", "AuthService", "src/services/auth_service.py", "Google OAuth and user management"),
        ("workspace", "WorkspaceService", "src/services/workspace_service.py", "Workspace and team management"),
        ("demo", "DemoService", "src/services/demo_service.py", "Demo data management"),
        ("session_manager", "SessionManager", "src/services/session_manager.py", "ADK session lifecycle management"),
        ("vapi", "VapiService", "src/services/vapi_service.py", "VAPI outbound calls"),
        ("whatsapp", "WhatsAppService", "src/services/whatsapp_service.py", "Twilio WhatsApp messaging"),
        ("meta_whatsapp", "MetaWhatsAppService", "src/services/meta_whatsapp_service.py", "Meta WhatsApp Cloud API"),
        ("teams", "TeamsService", "src/services/teams_service.py", "Microsoft Teams notifications"),
        ("google_calendar", "GoogleCalendarService", "src/services/google_calendar_service.py", "Calendar integration"),
        ("google_drive", "GoogleDriveService", "src/services/google_drive_service.py", "Document storage"),
        ("screening_notes", "ScreeningNotesIntegrationService", "src/services/screening_notes_integration_service.py", "Screening notes documents"),
        ("workflow", "WorkflowService", "src/services/workflow_service.py", "Workflow orchestration"),
    ]
    for id_suffix, name, file_path, desc in services:
        nodes.append(ArchitectureNode(
            id=f"service:{id_suffix}",
            type="service",
            name=name,
            layer="service",
            file_path=file_path,
            description=desc,
        ))

    # Repository Layer
    repositories = [
        ("vacancy", "VacancyRepository", "Vacancy data access"),
        ("application", "ApplicationRepository", "Application data access"),
        ("candidate", "CandidateRepository", "Candidate data access"),
        ("pre_screening", "PreScreeningRepository", "Pre-screening data access"),
        ("conversation", "ConversationRepository", "Conversation data access"),
        ("activity", "ActivityRepository", "Activity data access"),
        ("scheduled_interview", "ScheduledInterviewRepository", "Scheduled interview data access"),
        ("document_verification", "DocumentVerificationRepository", "Document verification data access"),
        ("agent_vacancy", "AgentVacancyRepository", "Agent vacancy data access"),
        ("user_profile", "UserProfileRepository", "User profile data access"),
        ("workspace", "WorkspaceRepository", "Workspace data access"),
        ("workspace_membership", "WorkspaceMembershipRepository", "Workspace membership data access"),
    ]
    for id_suffix, name, desc in repositories:
        nodes.append(ArchitectureNode(
            id=f"repo:{id_suffix}",
            type="repository",
            name=name,
            layer="repository",
            file_path=f"src/repositories/{id_suffix}_repo.py",
            description=desc,
        ))

    # Agent Layer
    agents = [
        ("interview_generator", "Interview Generator", "interview_generator/agent.py", "Generates knockout and qualification questions"),
        ("transcript_processor", "Transcript Processor", "transcript_processor/agent.py", "Analyzes voice call transcripts"),
        ("pre_screening_whatsapp", "Pre-screening WhatsApp", "pre_screening_whatsapp_agent/agent.py", "WhatsApp screening conversations"),
        ("cv_analyzer", "CV Analyzer", "cv_analyzer/agent.py", "CV analysis and parsing"),
        ("document_collection", "Document Collection", "document_collection_agent/agent.py", "Document upload handling"),
        ("document_recognition", "Document Recognition", "document_recognition_agent/agent.py", "ID document verification"),
        ("data_query", "Data Query", "data_query_agent/agent.py", "Natural language database queries"),
        ("recruiter_analyst", "Recruiter Analyst", "recruiter_analyst/agent.py", "Recruitment analytics"),
        ("candidate_simulator", "Candidate Simulator", "candidate_simulator/agent.py", "Testing persona simulation"),
    ]
    for id_suffix, name, file_path, desc in agents:
        nodes.append(ArchitectureNode(
            id=f"agent:{id_suffix}",
            type="agent",
            name=name,
            layer="agent",
            file_path=file_path,
            description=desc,
            metadata={"model": "gemini-2.0-flash"},
        ))

    # External Integrations
    externals = [
        ("vapi", "VAPI", "Voice AI platform for phone screening"),
        ("twilio", "Twilio", "WhatsApp messaging via Twilio API"),
        ("elevenlabs", "ElevenLabs", "Voice synthesis and phone screening"),
        ("google_calendar", "Google Calendar", "Interview scheduling"),
        ("google_drive", "Google Drive", "Document storage"),
        ("supabase", "Supabase", "PostgreSQL database"),
    ]
    for id_suffix, name, desc in externals:
        nodes.append(ArchitectureNode(
            id=f"external:{id_suffix}",
            type="external",
            name=name,
            layer="external",
            description=desc,
        ))

    return nodes


def _get_edges() -> list[ArchitectureEdge]:
    """Build all architecture edges (relationships)."""
    edges = []

    # Router -> Service relationships
    router_service_edges = [
        ("router:vacancies", "service:vacancy"),
        ("router:vacancies", "service:activity"),
        ("router:applications", "service:application"),
        ("router:applications", "service:vacancy"),
        ("router:candidates", "service:activity"),
        ("router:interviews", "service:interview"),
        ("router:interviews", "service:session_manager"),
        ("router:pre_screenings", "service:pre_screening"),
        ("router:pre_screenings", "service:session_manager"),
        ("router:screening", "service:session_manager"),
        ("router:webhooks", "service:pre_screening"),
        ("router:webhooks", "service:activity"),
        ("router:webhooks", "service:whatsapp"),
        ("router:vapi", "service:vapi"),
        ("router:vapi", "service:activity"),
        ("router:vapi", "service:scheduling"),
        ("router:outbound", "service:vapi"),
        ("router:outbound", "service:activity"),
        ("router:outbound", "service:workflow"),
        ("router:scheduling", "service:scheduling"),
        ("router:scheduling", "service:google_calendar"),
        ("router:auth", "service:auth"),
        ("router:workspaces", "service:workspace"),
        ("router:data_query", "service:session_manager"),
        ("router:demo", "service:demo"),
        ("router:demo", "service:workflow"),
        ("router:monitoring", "service:activity"),
        ("router:activities", "service:workflow"),
        ("router:teams", "service:teams"),
        ("router:document_collection", "service:session_manager"),
    ]
    for source, target in router_service_edges:
        edges.append(ArchitectureEdge(source=source, target=target, type="uses"))

    # Router -> Repository relationships (direct)
    router_repo_edges = [
        ("router:vacancies", "repo:vacancy"),
        ("router:applications", "repo:application"),
        ("router:candidates", "repo:candidate"),
        ("router:agents", "repo:agent_vacancy"),
        ("router:outbound", "repo:candidate"),
        ("router:outbound", "repo:vacancy"),
    ]
    for source, target in router_repo_edges:
        edges.append(ArchitectureEdge(source=source, target=target, type="uses"))

    # Router -> Agent relationships
    router_agent_edges = [
        ("router:interviews", "agent:interview_generator"),
        ("router:cv", "agent:cv_analyzer"),
        ("router:data_query", "agent:data_query"),
        ("router:data_query", "agent:recruiter_analyst"),
        ("router:webhooks", "agent:transcript_processor"),
        ("router:webhooks", "agent:pre_screening_whatsapp"),
        ("router:vapi", "agent:transcript_processor"),
        ("router:screening", "agent:pre_screening_whatsapp"),
        ("router:screening", "agent:candidate_simulator"),
        ("router:document_collection", "agent:document_collection"),
        ("router:documents", "agent:document_recognition"),
    ]
    for source, target in router_agent_edges:
        edges.append(ArchitectureEdge(source=source, target=target, type="calls"))

    # Service -> Repository relationships
    service_repo_edges = [
        ("service:application", "repo:application"),
        ("service:application", "repo:candidate"),
        ("service:vacancy", "repo:vacancy"),
        ("service:pre_screening", "repo:pre_screening"),
        ("service:activity", "repo:activity"),
        ("service:candidate_context", "repo:candidate"),
        ("service:candidate_context", "repo:activity"),
        ("service:scheduling", "repo:scheduled_interview"),
        ("service:auth", "repo:user_profile"),
        ("service:auth", "repo:workspace"),
        ("service:auth", "repo:workspace_membership"),
        ("service:workspace", "repo:workspace"),
        ("service:workspace", "repo:workspace_membership"),
        ("service:workspace", "repo:user_profile"),
    ]
    for source, target in service_repo_edges:
        edges.append(ArchitectureEdge(source=source, target=target, type="uses"))

    # Service -> External relationships
    service_external_edges = [
        ("service:vapi", "external:vapi"),
        ("service:whatsapp", "external:twilio"),
        ("service:google_calendar", "external:google_calendar"),
        ("service:google_drive", "external:google_drive"),
        ("service:screening_notes", "external:google_drive"),
        ("service:screening_notes", "external:google_calendar"),
    ]
    for source, target in service_external_edges:
        edges.append(ArchitectureEdge(source=source, target=target, type="integrates"))

    # Router -> External (webhooks)
    webhook_external_edges = [
        ("router:webhooks", "external:twilio", "webhook"),
        ("router:webhooks", "external:elevenlabs", "webhook"),
        ("router:vapi", "external:vapi", "webhook"),
        ("router:elevenlabs", "external:elevenlabs", "config"),
    ]
    for source, target, label in webhook_external_edges:
        edges.append(ArchitectureEdge(source=source, target=target, type="integrates", label=label))

    # Repository -> External (database)
    for repo in ["vacancy", "application", "candidate", "pre_screening", "conversation",
                 "activity", "scheduled_interview", "document_verification", "agent_vacancy",
                 "user_profile", "workspace", "workspace_membership"]:
        edges.append(ArchitectureEdge(
            source=f"repo:{repo}",
            target="external:supabase",
            type="stores",
        ))

    # Agent -> External
    agent_external_edges = [
        ("agent:data_query", "external:supabase"),
    ]
    for source, target in agent_external_edges:
        edges.append(ArchitectureEdge(source=source, target=target, type="integrates"))

    return edges


def _get_groups() -> list[ArchitectureGroup]:
    """Build layer groups for visualization."""
    return [
        ArchitectureGroup(id="api", name="API Layer", layer="api", color="#4CAF50"),
        ArchitectureGroup(id="service", name="Services", layer="service", color="#2196F3"),
        ArchitectureGroup(id="repository", name="Repositories", layer="repository", color="#FF9800"),
        ArchitectureGroup(id="agent", name="AI Agents", layer="agent", color="#9C27B0"),
        ArchitectureGroup(id="external", name="External Services", layer="external", color="#607D8B"),
    ]


@router.get("/architecture")
async def get_architecture() -> ArchitectureResponse:
    """
    Get the backend architecture as JSON for visualization.

    Returns nodes (components), edges (relationships), and groups (layers)
    suitable for rendering with graph libraries like React Flow, D3.js, or vis.js.
    """
    nodes = _get_nodes()
    edges = _get_edges()
    groups = _get_groups()

    # Count nodes by type
    stats = ArchitectureStats(
        routers=len([n for n in nodes if n.type == "router"]),
        services=len([n for n in nodes if n.type == "service"]),
        repositories=len([n for n in nodes if n.type == "repository"]),
        agents=len([n for n in nodes if n.type == "agent"]),
        external=len([n for n in nodes if n.type == "external"]),
    )

    return ArchitectureResponse(
        nodes=nodes,
        edges=edges,
        groups=groups,
        metadata=ArchitectureMetadata(stats=stats),
    )
