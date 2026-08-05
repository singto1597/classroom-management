export interface Student {
  id: number
  user_id: number | null
  room_id: number | string
  discord_id: number | null
  discord_id_str: string | null
  student_no: number
  student_id: number | null
  prefix: string | null
  first_name: string
  last_name: string
  nickname: string | null
  birthday: string | null // ISO Date string (YYYY-MM-DD)
  class_role: string
  cleaning_duty: string | null
  olympic_camp: string | null
  portfolio: string | null
  target_faculty: string | null
  blood_group: string | null
  shirt_size: string | null
  food_allergy: string | null
  congenital_disease: string | null
  phone_number: string | null
  phone_number_parent: string | null
  phone_number_parent_relation: string | null
  line_id: string | null
  ig_username: string | null
  email: string | null
  address_house_no: string | null
  address_road: string | null
  address_sub_district: string | null
  address_district: string | null
  address_province: string | null
  address_post_code: string | null
  status: 'active' | 'inactive' | 'pending'
  created_at: string
  updated_at: string
  deleted_at: string | null

  is_admin?: boolean;
  permissions?: string[];
}
