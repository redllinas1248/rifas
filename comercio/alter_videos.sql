-- Ejecutar en phpMyAdmin
CREATE TABLE IF NOT EXISTS `publicaciones_videos` (
  `id`              INT(11)      NOT NULL AUTO_INCREMENT,
  `publicacion_id`  INT(11)      NOT NULL,
  `ruta`            VARCHAR(500) NOT NULL,
  `fecha`           DATETIME     DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `fk_vid_pub` (`publicacion_id`),
  CONSTRAINT `fk_vid_pub` FOREIGN KEY (`publicacion_id`)
    REFERENCES `publicaciones` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
