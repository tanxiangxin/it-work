"""Initial immutable schema, vector extension and knowledge generation."""

from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public")
    op.execute(
        "\nCREATE TABLE users (\n\temail VARCHAR(255) NOT NULL, \n\tname VARCHAR(80) NOT NULL, \n\trole VARCHAR(16) NOT NULL, \n\tpassword_hash TEXT NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (email)\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE knowledge_state (\n\tid INTEGER NOT NULL, \n\tgeneration INTEGER NOT NULL, \n\tPRIMARY KEY (id)\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE documents (\n\tname VARCHAR(255) NOT NULL, \n\tvisibility VARCHAR(16) NOT NULL, \n\tactive_version_id UUID, \n\tdeleted BOOLEAN NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id)\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE login_sessions (\n\tuser_id UUID NOT NULL, \n\ttoken_hash VARCHAR(64) NOT NULL, \n\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(user_id) REFERENCES users (id), \n\tUNIQUE (token_hash)\n)\n\n"
    )
    op.execute("CREATE INDEX ix_login_sessions_user_id ON login_sessions (user_id)")
    op.execute(
        "\nCREATE TABLE document_versions (\n\tdocument_id UUID NOT NULL, \n\tfilename VARCHAR(255) NOT NULL, \n\tstorage_key VARCHAR(255) NOT NULL, \n\tfile_hash VARCHAR(64) NOT NULL, \n\tindex_key VARCHAR(100) NOT NULL, \n\tstatus VARCHAR(20) NOT NULL, \n\terror TEXT, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (document_id, file_hash, index_key), \n\tFOREIGN KEY(document_id) REFERENCES documents (id)\n)\n\n"
    )
    op.execute("CREATE INDEX ix_document_versions_document_id ON document_versions (document_id)")
    op.execute(
        "\nCREATE TABLE conversations (\n\tuser_id UUID NOT NULL, \n\ttitle VARCHAR(120) NOT NULL, \n\tmode VARCHAR(16) NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(user_id) REFERENCES users (id)\n)\n\n"
    )
    op.execute("CREATE INDEX ix_conversations_user_id ON conversations (user_id)")
    op.execute(
        "\nCREATE TABLE request_traces (\n\trequest_id VARCHAR(36) NOT NULL, \n\tuser_id UUID NOT NULL, \n\tmodel_mode VARCHAR(16) NOT NULL, \n\tmodel VARCHAR(100) NOT NULL, \n\tduration_ms INTEGER NOT NULL, \n\tcalls INTEGER NOT NULL, \n\tusage JSON, \n\tstatus VARCHAR(20) NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(user_id) REFERENCES users (id)\n)\n\n"
    )
    op.execute("CREATE INDEX ix_request_traces_request_id ON request_traces (request_id)")
    op.execute(
        "\nCREATE TABLE chunks (\n\tversion_id UUID NOT NULL, \n\tordinal INTEGER NOT NULL, \n\tcontent TEXT NOT NULL, \n\theading TEXT NOT NULL, \n\tpage INTEGER, \n\tparagraph INTEGER, \n\tembedding VECTOR(1024) NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (version_id, ordinal), \n\tFOREIGN KEY(version_id) REFERENCES document_versions (id)\n)\n\n"
    )
    op.execute("CREATE INDEX ix_chunks_version_id ON chunks (version_id)")
    op.execute(
        "\nCREATE TABLE import_jobs (\n\tversion_id UUID NOT NULL, \n\tstatus VARCHAR(20) NOT NULL, \n\tattempts INTEGER NOT NULL, \n\terror TEXT, \n\theartbeat TIMESTAMP WITH TIME ZONE NOT NULL, \n\tstarted_at TIMESTAMP WITH TIME ZONE, \n\tcompleted_at TIMESTAMP WITH TIME ZONE, \n\tlease_token VARCHAR(36), \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (version_id), \n\tFOREIGN KEY(version_id) REFERENCES document_versions (id)\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE messages (\n\tconversation_id UUID NOT NULL, \n\trole VARCHAR(16) NOT NULL, \n\tcontent TEXT NOT NULL, \n\tstatus VARCHAR(20) NOT NULL, \n\tmodel_mode VARCHAR(16) NOT NULL, \n\tcitations JSON NOT NULL, \n\tanswerable BOOLEAN NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(conversation_id) REFERENCES conversations (id)\n)\n\n"
    )
    op.execute("CREATE INDEX ix_messages_conversation_id ON messages (conversation_id)")
    op.execute(
        "\nCREATE TABLE ticket_drafts (\n\tuser_id UUID NOT NULL, \n\tconversation_id UUID NOT NULL, \n\ttitle VARCHAR(120) NOT NULL, \n\tcategory VARCHAR(20) NOT NULL, \n\tdescription TEXT NOT NULL, \n\tsubmitted BOOLEAN NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(user_id) REFERENCES users (id), \n\tUNIQUE (conversation_id), \n\tFOREIGN KEY(conversation_id) REFERENCES conversations (id)\n)\n\n"
    )
    op.execute("CREATE INDEX ix_ticket_drafts_user_id ON ticket_drafts (user_id)")
    op.execute(
        "\nCREATE TABLE tickets (\n\tuser_id UUID NOT NULL, \n\tdraft_id UUID NOT NULL, \n\ttitle VARCHAR(120) NOT NULL, \n\tcategory VARCHAR(20) NOT NULL, \n\tdescription TEXT NOT NULL, \n\tlocation VARCHAR(120) NOT NULL, \n\tstatus VARCHAR(20) NOT NULL, \n\tidempotency_key VARCHAR(120) NOT NULL, \n\trequest_hash VARCHAR(64) NOT NULL, \n\tsources JSON NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (user_id, idempotency_key), \n\tFOREIGN KEY(user_id) REFERENCES users (id), \n\tUNIQUE (draft_id), \n\tFOREIGN KEY(draft_id) REFERENCES ticket_drafts (id)\n)\n\n"
    )
    op.execute("CREATE INDEX ix_tickets_user_id ON tickets (user_id)")
    op.execute(
        "\nCREATE TABLE ticket_replies (\n\tticket_id UUID NOT NULL, \n\tuser_id UUID NOT NULL, \n\tcontent TEXT NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(ticket_id) REFERENCES tickets (id), \n\tFOREIGN KEY(user_id) REFERENCES users (id)\n)\n\n"
    )
    op.execute("CREATE INDEX ix_ticket_replies_ticket_id ON ticket_replies (ticket_id)")
    op.execute(
        "\nCREATE TABLE ticket_events (\n\tticket_id UUID NOT NULL, \n\tuser_id UUID NOT NULL, \n\tbefore VARCHAR(20), \n\tafter VARCHAR(20) NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(ticket_id) REFERENCES tickets (id), \n\tFOREIGN KEY(user_id) REFERENCES users (id)\n)\n\n"
    )
    op.execute("CREATE INDEX ix_ticket_events_ticket_id ON ticket_events (ticket_id)")
    op.execute("INSERT INTO knowledge_state (id, generation) VALUES (1, 0)")


def downgrade():
    op.execute("DROP TABLE ticket_replies")
    op.execute("DROP TABLE ticket_events")
    op.execute("DROP TABLE tickets")
    op.execute("DROP TABLE ticket_drafts")
    op.execute("DROP TABLE messages")
    op.execute("DROP TABLE import_jobs")
    op.execute("DROP TABLE chunks")
    op.execute("DROP TABLE request_traces")
    op.execute("DROP TABLE login_sessions")
    op.execute("DROP TABLE document_versions")
    op.execute("DROP TABLE conversations")
    op.execute("DROP TABLE users")
    op.execute("DROP TABLE knowledge_state")
    op.execute("DROP TABLE documents")
    # The shared vector extension is intentionally retained.
