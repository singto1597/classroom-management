<?php
require_once 'config/database.php';
require_once 'controllers/AuthController.php';

(new AuthController())->selectRoom();