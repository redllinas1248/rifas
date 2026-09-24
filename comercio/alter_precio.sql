-- Ejecutar esto en phpMyAdmin si la columna precio no existe
ALTER TABLE `publicaciones` ADD COLUMN `precio` DECIMAL(10,2) DEFAULT NULL AFTER `contenido`;
