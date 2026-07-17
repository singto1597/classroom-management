export interface UserRoom {
  room_id: number;
  server_id?: string;
  server_id_str?: string;
  room_code?: string;
  room_name: string;
  role: string;
  status: string; 

  is_admin?: boolean;
  permissions?: string[];
}