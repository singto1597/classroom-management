<form method="POST" action="index.php?page=students_edit&no=<?= $profile['student_no'] ?>">
    <input type="hidden" name="csrf_token" value="<?= $_SESSION['csrf_token'] ?>">
    
    <div class="d-flex justify-content-between align-items-center mb-4">
        <h3>✏️ แก้ไขข้อมูลโปรไฟล์ (#<?= $profile['student_no'] ?>)</h3>
        <button type="submit" class="btn btn-success fw-bold px-4 shadow-sm">💾 บันทึกการเปลี่ยนแปลง</button>
    </div>

    <div class="row g-4">
        <div class="col-md-6">
            <div class="card h-100 shadow-sm border-0">
                <div class="card-header bg-primary text-white fw-bold">🔵 ข้อมูลส่วนตัวหลัก</div>
                <div class="card-body">
                    <div class="mb-3"><label class="form-label small">รหัสนักเรียน</label><input type="text" name="student_id" class="form-control" value="<?= h($profile['student_id']) ?>"></div>
                    <div class="row">
                        <div class="col-4"><label class="form-label small">คำนำหน้า</label><input type="text" name="prefix" class="form-control" value="<?= h($profile['prefix']) ?>"></div>
                        <div class="col-8"><label class="form-label small">ชื่อเล่น</label><input type="text" name="nickname" class="form-control" value="<?= h($profile['nickname']) ?>"></div>
                    </div>
                </div>
            </div>
        </div>

        <div class="col-md-6">
            <div class="card h-100 shadow-sm border-0">
                <div class="card-header bg-danger text-white fw-bold">🔴 ข้อมูลสุขภาพ</div>
                <div class="card-body">
                    <div class="row mb-3">
                        <div class="col-6"><label class="form-label small">กรุ๊ปเลือด</label><input type="text" name="blood_group" class="form-control" value="<?= h($profile['blood_group']) ?>"></div>
                        <div class="col-6"><label class="form-label small">ไซส์เสื้อ</label><input type="text" name="shirt_size" class="form-control" value="<?= h($profile['shirt_size']) ?>"></div>
                    </div>
                    <div class="mb-3"><label class="form-label small">โรคประจำตัว/แพ้อาหาร</label><input type="text" name="food_allergy" class="form-control" value="<?= h($profile['food_allergy']) ?>"></div>
                </div>
            </div>
        </div>
        
        <div class="col-md-6">
            <div class="card h-100 shadow-sm border-0">
                <div class="card-header bg-info text-white fw-bold">🟣 ข้อมูลการติดต่อ</div>
                <div class="card-body">
                    <div class="mb-3"><label class="form-label small">เบอร์โทรศัพท์</label><input type="text" name="phone_number" class="form-control" value="<?= h($profile['phone_number']) ?>"></div>
                    <div class="row">
                        <div class="col-6"><label class="form-label small">เบอร์ผู้ปกครอง</label><input type="text" name="phone_number_parent" class="form-control" value="<?= h($profile['phone_number_parent']) ?>"></div>
                        <div class="col-6"><label class="form-label small">เกี่ยวข้องเป็น</label><input type="text" name="phone_number_parent_relation" class="form-control" value="<?= h($profile['phone_number_parent_relation']) ?>"></div>
                    </div>
                    <div class="row mt-2">
                        <div class="col-6"><label class="form-label small">Line ID</label><input type="text" name="line_id" class="form-control" value="<?= h($profile['line_id']) ?>"></div>
                        <div class="col-6"><label class="form-label small">IG Username</label><input type="text" name="ig_username" class="form-control" value="<?= h($profile['ig_username']) ?>"></div>
                    </div>
                </div>
            </div>
        </div>
        
        <div class="col-12">
            <div class="card shadow-sm border-0">
                <div class="card-header bg-warning text-dark fw-bold">📚 วิชาการและผลงานเด่น</div>
                <div class="card-body">
                    <div class="row">
                        <div class="col-md-6 mb-3"><label class="form-label small">คณะที่ใฝ่ฝัน</label><input type="text" name="target_faculty" class="form-control" value="<?= h($profile['target_faculty']) ?>"></div>
                        <div class="col-md-6 mb-3"><label class="form-label small">เวรทำความสะอาด</label><input type="text" name="cleaning_duty" class="form-control" value="<?= h($profile['cleaning_duty']) ?>"></div>
                        <div class="col-12 mb-3"><label class="form-label small">สอวน. / ค่ายวิชาการ</label><textarea name="olympic_camp" class="form-control" rows="2"><?= h($profile['olympic_camp']) ?></textarea></div>
                        <div class="col-12"><label class="form-label small">ผลงาน / รางวัลที่เคยได้รับ (พิมพ์ยาวๆ ได้เลย)</label><textarea name="portfolio" class="form-control" rows="5"><?= h($profile['portfolio']) ?></textarea></div>
                    </div>
                </div>
            </div>
        </div>


        <div class="col-md-12">
            <div class="card shadow-sm border-0">
                <div class="card-header bg-secondary text-white fw-bold">🟤 ข้อมูลที่อยู่ตามทะเบียนบ้าน</div>
                <div class="card-body">
                    <div class="row g-3">
                        <div class="col-md-3"><label class="form-label small">บ้านเลขที่/หมู่/ซอย</label><input type="text" name="address_house_no" class="form-control" value="<?= h($profile['address_house_no']) ?>"></div>
                        <div class="col-md-3"><label class="form-label small">ถนน</label><input type="text" name="address_road" class="form-control" value="<?= h($profile['address_road']) ?>"></div>
                        <div class="col-md-3"><label class="form-label small">ตำบล</label><input type="text" name="address_sub_district" class="form-control" value="<?= h($profile['address_sub_district']) ?>"></div>
                        <div class="col-md-3"><label class="form-label small">อำเภอ</label><input type="text" name="address_district" class="form-control" value="<?= h($profile['address_district']) ?>"></div>
                        <div class="col-md-4"><label class="form-label small">จังหวัด</label><input type="text" name="address_province" class="form-control" value="<?= h($profile['address_province']) ?>"></div>
                        <div class="col-md-4"><label class="form-label small">รหัสไปรษณีย์</label><input type="text" name="address_post_code" class="form-control" value="<?= h($profile['address_post_code']) ?>"></div>
                    </div>
                </div>
            </div>
        </div>
    </div>
</form>