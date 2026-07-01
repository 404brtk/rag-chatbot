from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            CREATE EXTENSION IF NOT EXISTS unaccent;

            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_ts_dict WHERE dictname = 'polish_hunspell') THEN
                    CREATE TEXT SEARCH DICTIONARY polish_hunspell (
                        TEMPLATE = ispell,
                        DictFile = polish,
                        AffFile = polish,
                        StopWords = polish
                    );
                END IF;
            END
            $$;

            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_ts_config WHERE cfgname = 'polish') THEN
                    CREATE TEXT SEARCH CONFIGURATION polish (COPY = english);

                    ALTER TEXT SEARCH CONFIGURATION polish
                        ALTER MAPPING FOR word, asciiword, hword, hword_part, asciihword
                        WITH unaccent, polish_hunspell, simple;
                END IF;
            END
            $$;
            """,
            reverse_sql="""
            DROP TEXT SEARCH CONFIGURATION IF EXISTS polish;
            DROP TEXT SEARCH DICTIONARY IF EXISTS polish_hunspell;
            """,
        )
    ]
