</div> <!-- ปิด container -->
    <footer class="mt-5 mb-4 text-center text-muted">
        <small>&copy; 2026 Classroom-Sync Project By <a href = "https://github.com/singto1597" target="_blank">เด็กชายพัฒนพล สุธรรม</a> </small>
    </footer>

    <?php
    $flash_success = $_SESSION['success_msg'] ?? null;
    $flash_error = $_SESSION['error_msg'] ?? null;
    $flash_abort = $_SESSION['error_message'] ?? null;
    unset($_SESSION['success_msg'], $_SESSION['error_msg']);
    ?>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>

    <?php if (!empty($flash_success)): ?>
    <script>
    Swal.fire({
        icon: 'success',
        title: 'สำเร็จ!',
        text: <?= json_encode($flash_success, JSON_HEX_TAG | JSON_HEX_APOS | JSON_HEX_QUOT | JSON_HEX_AMP | JSON_UNESCAPED_UNICODE); ?>
    });
    </script>
    <?php endif; ?>

    <?php if (!empty($flash_error)): ?>
    <script>
    Swal.fire({
        icon: 'error',
        title: 'ผิดพลาด',
        text: <?= json_encode($flash_error, JSON_HEX_TAG | JSON_HEX_APOS | JSON_HEX_QUOT | JSON_HEX_AMP | JSON_UNESCAPED_UNICODE); ?>
    });
    </script>
    <?php endif; ?>

    <?php if (!empty($flash_abort)):
        unset($_SESSION['error_message']);
    ?>
    <script>
    Swal.fire({
        icon: 'error',
        title: 'เกิดข้อผิดพลาด',
        text: <?= json_encode((string)$flash_abort, JSON_HEX_TAG | JSON_HEX_APOS | JSON_HEX_QUOT | JSON_HEX_AMP | JSON_UNESCAPED_UNICODE); ?>
    });
    </script>
    <?php endif; ?>
</body>
</html>
