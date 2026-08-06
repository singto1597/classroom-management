// 📢 Web → Discord ประกาศ (CUSTOM_MESSAGE event)
// แมปจาก backend/models/action_schemas.py

export interface CustomMessageRequest {
  title: string;
  message: string;
  user_name: string;
}

export interface CustomMessageResponse {
  status: string;
  message: string;
}
