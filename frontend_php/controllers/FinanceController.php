<?php
require_once 'models/Finance.php';

class FinanceController {
    private $financeModel;

    public function __construct() {
        $this->financeModel = new Finance();
    }

    // 📍 1. หน้า Dashboard สรุปการเงิน
    public function dashboard() {
        $room_id = $_SESSION['room_id'];
        
        $month = $_GET['month'] ?? null;
        $year = $_GET['year'] ?? null;

        try {
            $summary = $this->financeModel->getSummary($room_id, $month, $year);
            $accounts = $this->financeModel->getAccounts($room_id);
            
            require 'views/finance/dashboard.php';
        } catch (Exception $e) {
            abort("API Error: " . $e->getMessage());
        }
    }

    // 📍 2. หน้าจัดการกระเป๋าเงินและหมวดหมู่ (Settings)
    public function accountsAndCategories() {
        $room_id = $_SESSION['room_id'];
        
        if ($_SESSION['role'] === 'student') {
            abort("🛑 คุณไม่มีสิทธิ์จัดการการตั้งค่าการเงินครับ");
        }

        try {
            $accounts = $this->financeModel->getAccounts($room_id);
            $categories_inc = $this->financeModel->getCategories($room_id, 'income');
            $categories_exp = $this->financeModel->getCategories($room_id, 'expense');
            
            require 'views/finance/accounts_categories.php';
        } catch (Exception $e) {
            abort("เกิดข้อผิดพลาดในการโหลดข้อมูลตั้งค่า: " . $e->getMessage());
        }
    }

    // 📍 3. ตัวจัดการ Action (POST) ทั้งหมดสำหรับ Finance
    public function handleAction() {
        $is_json = isset($_GET['format']) && $_GET['format'] === 'json';

        if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
            if ($is_json) {
                http_response_code(405);
                header('Content-Type: application/json; charset=utf-8');
                echo json_encode(['status' => 'error', 'message' => 'ใช้ได้เฉพาะ POST เท่านั้น']);
                exit();
            }
            header('Location: index.php?page=finance_dashboard');
            exit();
        }

        if (!isset($_POST['csrf_token']) || $_POST['csrf_token'] !== $_SESSION['csrf_token']) {
            if ($is_json) {
                http_response_code(403);
                echo json_encode(['status' => 'error', 'message' => 'Invalid CSRF Token']);
                exit();
            }
            abort("Invalid CSRF Token");
        }

        $room_id = $_SESSION['room_id'];
        $action = $_POST['action'] ?? '';
        $user_name = $_SESSION['user_name'];

        if ($_SESSION['role'] === 'student') {
            if ($is_json) {
                http_response_code(403);
                echo json_encode(['status' => 'error', 'message' => 'คุณไม่มีสิทธิ์ทำรายการนี้']);
                exit();
            }
            abort("🛑 สิทธิ์การเข้าถึงถูกปฏิเสธ");
        }

        try {
            $success_msg = ""; 

            switch ($action) {
                // --- จัดการบัญชี ---
                case 'add_account':
                    $payload = [
                        "account_name" => trim($_POST['account_name']),
                        "initial_balance" => (float)$_POST['initial_balance']
                    ];
                    $this->financeModel->createAccount($room_id, $payload);
                    $success_msg = "เพิ่มกระเป๋าเงินใหม่สำเร็จ!";
                    break;
                case 'edit_account':
                    $acc_id = (int)$_POST['account_id'];
                    $new_name = trim($_POST['account_name']);
                    $this->financeModel->updateAccount($room_id, $acc_id, $new_name);
                    $success_msg = "แก้ไขชื่อบัญชีสำเร็จ";
                    break;
                case 'delete_account':
                    $acc_id = (int)$_POST['account_id'];
                    $this->financeModel->deleteAccount($room_id, $acc_id);
                    $success_msg = "ลบบัญชีสำเร็จ";
                    break;

                // --- จัดการหมวดหมู่ ---
                case 'add_category':
                    $payload = [
                        "category_name" => trim($_POST['category_name']),
                        "category_type" => $_POST['category_type']
                    ];
                    $this->financeModel->createCategory($room_id, $payload);
                    $success_msg = "เพิ่มหมวดหมู่สำเร็จ";
                    break;
                case 'edit_category':
                    $cat_id = (int)$_POST['category_id'];
                    $this->financeModel->updateCategory($room_id, $cat_id, trim($_POST['category_name']));
                    $success_msg = "แก้ไขชื่อหมวดหมู่สำเร็จ";
                    break;
                case 'delete_category':
                    $cat_id = (int)$_POST['category_id'];
                    $this->financeModel->deleteCategory($room_id, $cat_id);
                    $success_msg = "ลบหมวดหมู่สำเร็จ";
                    break;

                // --- ระบบรับ-จ่าย-โอน ---
                case 'add_transaction':
                    $payload = [
                        "account_id" => (int)$_POST['account_id'],
                        "category_id" => (int)$_POST['category_id'],
                        "amount" => (float)$_POST['amount'],
                        "description" => trim($_POST['description']),
                        "transaction_type" => $_POST['transaction_type'],
                        "slip_image_url" => !empty($_POST['slip_image_url']) ? trim($_POST['slip_image_url']) : null,
                        "user_name" => $user_name
                    ];
                    $this->financeModel->addTransaction($room_id, $payload);
                    $success_msg = "บันทึกรายการสำเร็จ!";
                    break;
                case 'transfer_money':
                    $payload = [
                        "from_account_id" => (int)$_POST['from_account_id'],
                        "to_account_id" => (int)$_POST['to_account_id'],
                        "amount" => (float)$_POST['amount'],
                        "description" => trim($_POST['description']),
                        "user_name" => $user_name
                    ];
                    $this->financeModel->transferMoney($room_id, $payload);
                    $success_msg = "โอนเงินสำเร็จ!";
                    break;
                case 'revert_transaction':
                    $trans_id = (int)$_POST['transaction_id'];
                    $this->financeModel->revertTransaction($room_id, $trans_id, $user_name);
                    $success_msg = "ยกเลิกรายการและคืนเงินสำเร็จ!";
                    break;
                
                // --- ระบบเก็บเงิน (Collections & Payments) ---
                case 'create_collection':
                    $payload = [
                        "title" => trim($_POST['title']),
                        "amount" => (float)$_POST['amount'],
                        "due_date" => $_POST['due_date']
                    ];
                    $res = $this->financeModel->createCollection($room_id, $payload);
                    $success_msg = $res['message'] ?? "สร้างการเรียกเก็บเงินสำเร็จ";
                    break;
                case 'update_collection':
                    $col_id = (int)$_POST['collection_id'];
                    $payload = [];
                    if (!empty($_POST['amount'])) $payload['amount'] = (float)$_POST['amount'];
                    if (!empty($_POST['due_date'])) $payload['due_date'] = $_POST['due_date'];
                    if (!empty($_POST['status'])) $payload['status'] = $_POST['status'];
                    if (!empty($_POST['title'])) $payload['title'] = trim($_POST['title']);
                    $this->financeModel->updateCollection($room_id, $col_id, $payload);
                    $success_msg = "อัปเดตแคมเปญสำเร็จ";
                    break;
                case 'confirm_payment':
                    $payment_id = (int)$_POST['payment_id'];
                    $payload = [
                        "paid_to_account_id" => (int)$_POST['paid_to_account_id'],
                        "paid_amount" => (float)$_POST['paid_amount'],
                        "slip_image_url" => !empty($_POST['slip_image_url']) ? trim($_POST['slip_image_url']) : null,
                        "user_name" => $user_name
                    ];
                    $this->financeModel->confirmPayment($room_id, $payment_id, $payload);
                    $success_msg = "ยืนยันการรับเงินสำเร็จ!";
                    break;

                // ==========================================
                // 🌟 ส่วนที่เพิ่มใหม่: จัดการ Batch Payment
                // ==========================================
                case 'get_student_debts':
                    $student_id = (int)$_POST['student_id'];
                    $debts_data = $this->financeModel->getStudentDebts($room_id, $student_id);
                    http_response_code(200);
                    echo json_encode(['status' => 'success', 'data' => $debts_data]);
                    exit();

                case 'batch_pay_debt':
                    $paid_to_account_id = (int)$_POST['paid_to_account_id'];
                    $slip_image_url = !empty($_POST['slip_image_url']) ? trim($_POST['slip_image_url']) : null;
                    $payment_ids = $_POST['payment_ids'] ?? [];
                    $pay_amounts = $_POST['pay_amounts'] ?? [];

                    if (empty($payment_ids)) {
                        throw new Exception("ไม่ได้เลือกรายการที่ต้องการชำระ");
                    }

                    foreach ($payment_ids as $pid) {
                        $p_amount = (float)($pay_amounts[$pid] ?? 0);
                        if ($p_amount <= 0) continue;

                        $payload = [
                            "paid_to_account_id" => $paid_to_account_id,
                            "paid_amount" => $p_amount,
                            "slip_image_url" => $slip_image_url,
                            "user_name" => $user_name
                        ];
                        // ยิงทีละรายการ (ทางเลือก A - ง่ายและใช้ API ตัวเดิมได้เลย)
                        $this->financeModel->confirmPayment($room_id, $pid, $payload);
                    }
                    $success_msg = "รับเงินรวบยอดสำเร็จ " . count($payment_ids) . " รายการ!";
                    break;

                default:
                    throw new Exception("ไม่พบ Action ที่ระบุ");
            }

            if ($is_json) {
                http_response_code(200);
                echo json_encode(['status' => 'success', 'message' => $success_msg]);
                exit();
            } else {
                $_SESSION['success_msg'] = $success_msg;
                // 🌟 Smart Redirect: เด้งไปหน้าให้ถูกหมวดหมู่
                $target_page = 'finance_dashboard';
                if (in_array($action, ['add_account', 'edit_account', 'delete_account', 'add_category', 'edit_category', 'delete_category'])) $target_page = 'finance_accounts';
                if (in_array($action, ['add_transaction', 'transfer_money', 'revert_transaction'])) $target_page = 'finance_transactions';
                if (in_array($action, ['create_collection'])) $target_page = 'finance_collections';
                if (in_array($action, ['update_collection', 'confirm_payment'])) $target_page = 'finance_collections_view&id=' . ($_POST['collection_id'] ?? $_GET['id'] ?? '');
                if (in_array($action, ['batch_pay_debt'])) $target_page = 'finance_debtors';
                
                header("Location: index.php?page=" . $target_page);
                exit();
            }

        } catch (Exception $e) {
            if ($is_json) {
                http_response_code(400); 
                echo json_encode(['status' => 'error', 'message' => $e->getMessage()]);
                exit();
            }
            abort("จัดการข้อมูลผิดพลาด: " . $e->getMessage());
        }
    }

    // 📍 4. ประวัติรายการ (Transactions List)
    public function transactionHistory() {
        $room_id = $_SESSION['room_id'];
        $is_json = isset($_GET['format']) && $_GET['format'] === 'json';
        
        $limit = isset($_GET['limit']) ? (int)$_GET['limit'] : 50; 
        $page = isset($_GET['p']) ? max(1, (int)$_GET['p']) : 1;
        $offset = ($page - 1) * $limit;

        $filters = [
            'limit' => $limit,
            'offset' => $offset,
            'transaction_type' => !empty($_GET['type']) ? $_GET['type'] : null,
            'start_date' => !empty($_GET['start_date']) ? $_GET['start_date'] : null,
            'end_date' => !empty($_GET['end_date']) ? $_GET['end_date'] : null,
        ];

        try {
            $api_response = $this->financeModel->getTransactions($room_id, array_filter($filters));
            
            if ($is_json) {
                http_response_code(200);
                header('Content-Type: application/json; charset=utf-8');
                echo json_encode(['status' => 'success', 'data' => $api_response]);
                exit();
            }

            $accounts = $this->financeModel->getAccounts($room_id);
            require 'views/finance/transactions/list.php';
        } catch (Exception $e) { 
            if ($is_json) { echo json_encode(['status' => 'error']); exit(); }
            abort($e->getMessage()); 
        }
    }

    // 📍 5. ฟอร์มเพิ่มรายการ (Add Transaction)
    public function addTransactionForm() {
        $room_id = $_SESSION['room_id'];
        try {
            $accounts = $this->financeModel->getAccounts($room_id);
            $categories_inc = $this->financeModel->getCategories($room_id, 'income');
            $categories_exp = $this->financeModel->getCategories($room_id, 'expense');
            require 'views/finance/transactions/add.php';
        } catch (Exception $e) { abort($e->getMessage()); }
    }

    // 📍 6. ลิสต์แคมเปญเก็บเงิน (Collections List)
    public function collectionsList() {
        $room_id = $_SESSION['room_id'];
        try {
            $collections = $this->financeModel->getCollections($room_id);
            require 'views/finance/collections/list.php';
        } catch (Exception $e) { abort($e->getMessage()); }
    }

    // 📍 7. หน้ารายละเอียดการเก็บเงิน 1 แคมเปญ (Collection View)
    public function collectionView() {
        $room_id = $_SESSION['room_id'];
        $collection_id = $_GET['id'] ?? null;
        if (!$collection_id) abort("ระบุ ID แคมเปญไม่ถูกต้อง");
        
        try {
            $data = $this->financeModel->getCollectionStatus($room_id, $collection_id);
            $accounts = $this->financeModel->getAccounts($room_id);
            require 'views/finance/collections/view.php';
        } catch (Exception $e) { abort($e->getMessage()); }
    }

    // 📍 8. หน้าทวงหนี้รวม (Batch Debtors)
    public function debtorsList() {
        $room_id = $_SESSION['room_id'];
        try {
            $debtors = $this->financeModel->getAllDebtors($room_id);
            // 🌟 เพิ่มบรรทัดนี้ เพื่อส่งบัญชีรับเงินไปให้ Dropdown ใน Modal
            $accounts = $this->financeModel->getAccounts($room_id); 
            require 'views/finance/debtors/list.php';
        } catch (Exception $e) { abort($e->getMessage()); }
    }
}
