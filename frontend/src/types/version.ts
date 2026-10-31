// 🔖 เวอร์ชันที่ backend รันอยู่จริง — แมปจาก backend/models/version_schemas.py
export interface VersionInfo {
  version: string;
  git_sha: string;
  service: string;
}
