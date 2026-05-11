<?php
require_once 'services/ApiClient.php';

class Finance {
    private $api;

    public function __construct() {
        $this->api = new ApiClient();
    }

    // ==========================================
    // 💰 1. Accounts & Categories
    // ==========================================
    public function getAccounts($room_id) {
        return $this->api->request('GET', "{$room_id}/finance/accounts");
    }

    public function createAccount($room_id, $payload) {
        return $this->api->request('POST', "{$room_id}/finance/accounts", ['json' => $payload]);
    }

    public function updateAccount($room_id, $account_id, $name) {
        return $this->api->request('PATCH', "{$room_id}/finance/accounts/{$account_id}", ['json' => ['account_name' => $name]]);
    }

    public function deleteAccount($room_id, $account_id) {
        return $this->api->request('DELETE', "{$room_id}/finance/accounts/{$account_id}");
    }

    public function getCategories($room_id, $type = null) {
        $options = $type ? ['query' => ['cat_type' => $type]] : [];
        return $this->api->request('GET', "{$room_id}/finance/categories", $options);
    }

    // ==========================================
    // 💸 2. Transactions & Transfers
    // ==========================================
    public function addTransaction($room_id, $payload) {
        return $this->api->request('POST', "{$room_id}/finance/transactions", ['json' => $payload]);
    }

    public function getTransactions($room_id, $filters = []) {
        return $this->api->request('GET', "{$room_id}/finance/transactions", ['query' => $filters]);
    }

    public function transferMoney($room_id, $payload) {
        return $this->api->request('POST', "{$room_id}/finance/transfer", ['json' => $payload]);
    }

    public function revertTransaction($room_id, $transaction_id, $user_name) {
        return $this->api->request('DELETE', "{$room_id}/finance/transactions/{$transaction_id}", [
            'json' => ['user_name' => $user_name]
        ]);
    }

    // ==========================================
    // 📦 3. Fee Collections & Payments
    // ==========================================
    public function getCollections($room_id) {
        return $this->api->request('GET', "{$room_id}/finance/collections");
    }

    public function createCollection($room_id, $payload) {
        return $this->api->request('POST', "{$room_id}/finance/collections", ['json' => $payload]);
    }

    public function getCollectionStatus($room_id, $collection_id) {
        return $this->api->request('GET', "{$room_id}/finance/collections/{$collection_id}");
    }

    public function confirmPayment($room_id, $payment_id, $payload) {
        return $this->api->request('PUT', "{$room_id}/finance/payments/{$payment_id}/pay", ['json' => $payload]);
    }

    // ==========================================
    // 📊 4. Summary & Reports
    // ==========================================
    public function getSummary($room_id, $month = null, $year = null) {
        $query = array_filter(['month' => $month, 'year' => $year]);
        return $this->api->request('GET', "{$room_id}/finance/summary", ['query' => $query]);
    }

    public function getAllDebtors($room_id) {
        return $this->api->request('GET', "{$room_id}/finance/debtors");
    }

    public function getStudentDebts($room_id, $student_id) {
        return $this->api->request('GET', "{$room_id}/finance/students/{$student_id}/debts");
    }

    public function updateCollection($room_id, $collection_id, $payload) {
        return $this->api->request('PUT', "{$room_id}/finance/collections/{$collection_id}", ['json' => $payload]);
    }
}