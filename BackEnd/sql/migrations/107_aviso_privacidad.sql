-- =============================================================================
-- 107_aviso_privacidad.sql
-- Bloqueante de entrega: el sistema guarda datos de niños, la imagen de la INE
-- del tutor y fotografías sin aviso de privacidad ni consentimiento (LFPDPPP,
-- DOF 20-03-2025).
--
-- 1. avisos_privacidad: el aviso por versiones (texto integral, texto
--    simplificado y datos del responsable). La versión vigente es la de número
--    más alto; publicar una versión nueva nunca modifica las anteriores, para
--    poder demostrar qué texto aceptó cada tutor. Los textos llevan
--    marcadores {{...}} que la API reemplaza con los datos del responsable.
--    Formato: "# " título, "## " sección, "- " viñeta; párrafos separados por
--    una línea en blanco (el frontend lo muestra sin interpretar HTML).
-- 2. Versión 1 sembrada con una PLANTILLA: el AdministradorSistema debe
--    capturar los datos del responsable y un abogado revisar el texto antes de
--    usarla.
-- 3. registros: qué versión del aviso aceptó el tutor, cuándo, y si aceptó las
--    finalidades voluntarias (lealtad y promociones). Nulas en los registros
--    anteriores a esta migración.
-- Idempotente.
-- =============================================================================

CREATE TABLE IF NOT EXISTS public.avisos_privacidad (
    version                      INTEGER PRIMARY KEY CHECK (version > 0),
    texto_integral               TEXT NOT NULL,
    texto_simplificado           TEXT NOT NULL,
    razon_social                 VARCHAR(200) NOT NULL DEFAULT '',
    nombre_comercial             VARCHAR(150) NOT NULL DEFAULT '',
    domicilio                    VARCHAR(400) NOT NULL DEFAULT '',
    area_datos_personales        VARCHAR(150) NOT NULL DEFAULT '',
    correo_datos_personales      VARCHAR(150) NOT NULL DEFAULT '',
    telefono_datos_personales    VARCHAR(30)  NOT NULL DEFAULT '',
    url_aviso                    VARCHAR(300) NOT NULL DEFAULT '',
    dias_conservacion_imagenes   INTEGER NOT NULL DEFAULT 90
        CHECK (dias_conservacion_imagenes BETWEEN 1 AND 3650),
    anios_conservacion_registros INTEGER NOT NULL DEFAULT 5
        CHECK (anios_conservacion_registros BETWEEN 1 AND 20),
    motivo_cambio                TEXT,
    vigente_desde                TIMESTAMPTZ NOT NULL DEFAULT now(),
    publicado_por                UUID REFERENCES public.usuarios(id)
);

INSERT INTO public.avisos_privacidad (
    version, nombre_comercial, area_datos_personales, motivo_cambio,
    texto_integral, texto_simplificado
)
VALUES (
    1,
    'Woow Kids',
    'Departamento de Datos Personales',
    'Plantilla inicial (pendiente de revisión legal).',
$integral$# AVISO DE PRIVACIDAD INTEGRAL

Versión {{version}}. Vigente desde el {{fecha_vigencia}}.

## 1. Identidad y domicilio del responsable

{{razon_social}}, que opera comercialmente como «{{nombre_comercial}}» (el «Responsable»), con domicilio en {{domicilio}}, es responsable del tratamiento de los datos personales que usted nos proporcione, conforme a la Ley Federal de Protección de Datos Personales en Posesión de los Particulares publicada en el Diario Oficial de la Federación el 20 de marzo de 2025 (la «Ley») y demás disposiciones aplicables.

Para cualquier asunto relacionado con este aviso o con sus datos personales, puede contactar a nuestro {{area_datos_personales}} en el correo electrónico {{correo_datos_personales}} o en el teléfono {{telefono_datos_personales}}.

## 2. Datos personales que tratamos

Recabamos sus datos de manera personal en la recepción de nuestras sucursales y, cuando reserva un evento, en persona o por teléfono. Según el servicio que contrate, tratamos los siguientes datos:

- Del padre, madre o tutor que registra la entrada de un niño o niña: nombre completo, teléfono celular, parentesco con el menor, nombre de una segunda persona autorizada para recogerlo (si usted la designa), imagen de su identificación oficial (por ejemplo, la credencial para votar) y fotografías tomadas a su llegada.
- De los niños y niñas: nombre completo, edad, fotografías tomadas a su llegada y las observaciones que usted nos indique para su cuidado.
- De quien reserva un evento: nombre, apellidos, teléfono y, en su caso, correo electrónico y notas sobre el evento contratado.
- Para el programa de lealtad: número de teléfono celular e historial de puntos acumulados y canjeados.
- De los pagos: método de pago, monto y, en pagos con tarjeta o transferencia, el número de autorización o referencia. No guardamos el número completo de su tarjeta.

Datos personales sensibles. Las observaciones sobre la salud de los niños (por ejemplo, alergias, padecimientos o cuidados especiales) son datos personales sensibles. Solo las tratamos si usted decide proporcionarlas, únicamente para cuidar la integridad del menor durante su estancia, y con su consentimiento expreso y por escrito.

Datos de niñas, niños y adolescentes. Tratamos los datos de los menores únicamente con el consentimiento de quien ejerce la patria potestad o la tutela, conforme a las reglas de representación de la legislación civil aplicable. La persona que registra la entrada declara ser madre, padre o tutor del menor, o contar con su autorización para hacerlo.

Datos de terceros. Si usted nos proporciona datos de otra persona (por ejemplo, la segunda persona autorizada para recoger al menor), declara que le informó de este aviso y que cuenta con su consentimiento.

## 3. Finalidades del tratamiento

Finalidades necesarias. Son indispensables para prestar el servicio que usted solicita:

- Registrar la entrada y la salida de los niños y controlar el acceso a las áreas de juego.
- Identificar al adulto responsable y entregar a cada niño o niña únicamente a su tutor o a la persona autorizada, comparando sus datos, su identificación y las fotografías de llegada.
- Cuidar la seguridad e integridad de los niños durante su estancia, atender las indicaciones de salud que usted nos dé y localizar al tutor en caso de emergencia.
- Calcular y cobrar el tiempo de estancia, los productos y los servicios; emitir comprobantes y atender aclaraciones.
- Gestionar la reservación, el pago y la realización de eventos.
- Darle acceso al portal de padres mediante el código QR de su comprobante, para consultar el estado de la visita.
- Cumplir obligaciones legales y fiscales, y atender requerimientos de autoridades competentes.

Finalidades voluntarias. No son necesarias para el servicio y requieren su consentimiento; puede negarse sin que ello afecte el servicio que contrata:

- Acumular y canjear puntos del programa de lealtad, asociados a su teléfono celular.
- Enviarle promociones, ofertas e información de eventos de {{nombre_comercial}}.
- Invitarle a responder encuestas de calidad del servicio.

## 4. Cómo negarse a las finalidades voluntarias y limitar el uso de sus datos

- Al registrar la entrada, indique al personal de recepción que no desea que sus datos se usen para las finalidades voluntarias. Se dejará constancia en el sistema y no se acumularán puntos ni se le enviarán promociones.
- En cualquier momento, escriba a {{correo_datos_personales}} con el asunto «Negativa de finalidades voluntarias», indicando su nombre y teléfono.
- Puede inscribir su teléfono en el Registro Público para Evitar Publicidad (REPEP) de la Procuraduría Federal del Consumidor.

## 5. Transferencias y encargados

No transferimos sus datos personales a terceros sin su consentimiento, salvo en los casos que la Ley permite sin él (artículo 36), por ejemplo cuando lo exija una ley o una autoridad competente, cuando sea necesario para la atención médica de un menor en una emergencia, o para el reconocimiento, ejercicio o defensa de un derecho en un proceso judicial.

Algunos proveedores nos prestan servicios que implican el manejo de sus datos (por ejemplo, alojamiento y respaldo de la información, soporte técnico del sistema o procesamiento de pagos con tarjeta). Actúan como encargados: tratan los datos solo por cuenta del Responsable, según sus instrucciones y con obligación de confidencialidad. Esto no es una transferencia.

## 6. Derechos ARCO

Usted, o su representante legal, tiene derecho a conocer qué datos personales tenemos de usted y cómo los usamos (Acceso); a pedir que los corrijamos si están desactualizados, son inexactos o incompletos (Rectificación); a que los eliminemos de nuestros registros (Cancelación), y a oponerse a su uso para fines específicos (Oposición). Los derechos sobre los datos de un menor los ejerce quien ejerza su patria potestad o tutela.

Para ejercerlos, envíe su solicitud al correo {{correo_datos_personales}} o entréguela por escrito en {{domicilio}}. La solicitud debe contener:

- Su nombre y domicilio, o cualquier otro medio para recibir notificaciones.
- Los documentos que acrediten su identidad o, en su caso, la personalidad e identidad de su representante. Si la solicitud es sobre los datos de un menor, también el documento que acredite la patria potestad o la tutela.
- La descripción clara y precisa de los datos sobre los que ejerce el derecho, salvo que se trate del derecho de acceso.
- El derecho que desea ejercer o lo que solicita. Si pide una rectificación, indique la corrección y acompañe la documentación que la sustente.
- Cualquier otro dato que facilite localizar su información (por ejemplo, la fecha y la sucursal de la visita).

Le comunicaremos nuestra respuesta en un plazo máximo de veinte días hábiles contados desde que recibamos su solicitud y, si resulta procedente, la haremos efectiva dentro de los quince días hábiles siguientes. Estos plazos podrán ampliarse una sola vez por un periodo igual cuando las circunstancias del caso lo justifiquen. El acceso se dará mediante copias simples o documentos electrónicos.

El ejercicio de los derechos ARCO es gratuito; solo podrán cobrarse los costos de reproducción, copias o envío. Si no está conforme con nuestra respuesta, o no la recibe, puede acudir ante la Secretaría Anticorrupción y Buen Gobierno, autoridad en materia de protección de datos personales.

## 7. Revocación del consentimiento

Puede revocar en cualquier momento el consentimiento que nos haya otorgado, sin efectos retroactivos, con el mismo procedimiento y medios de la sección 6. En algunos casos no podremos atender su solicitud o concluir el tratamiento de inmediato, porque una obligación legal nos exija conservar ciertos datos. Si revoca el consentimiento para una finalidad necesaria, no podremos seguir prestándole el servicio relacionado con ella.

## 8. Plazo de conservación

- La imagen de la identificación del tutor, las fotografías de llegada y las observaciones de salud de los niños se conservan {{dias_conservacion_imagenes}} días naturales después de la visita, para aclarar cualquier incidente relacionado con la entrega de los menores. Después se eliminan de forma segura.
- Los datos de registro de visitas, cobros y eventos se conservan {{anios_conservacion_registros}} años, por obligaciones fiscales y mercantiles y para atender aclaraciones.
- Los datos del programa de lealtad se conservan mientras usted participe en él.

Cumplidos estos plazos, los datos se bloquean y se suprimen conforme a la Ley.

## 9. Medidas de seguridad

Mantenemos medidas de seguridad administrativas, técnicas y físicas para proteger sus datos contra daño, pérdida, alteración, destrucción o uso, acceso o tratamiento no autorizado. Entre ellas: acceso al sistema solo con usuario y contraseña y según el puesto de cada persona, imágenes guardadas en un almacenamiento que no es público, y respaldos periódicos. Si ocurre una vulneración de seguridad que afecte de forma significativa sus derechos, se lo informaremos de inmediato.

## 10. Uso de tecnologías

Nuestro sistema y el portal de padres no usan cookies publicitarias ni herramientas de rastreo de terceros. Solo usan el almacenamiento del navegador estrictamente necesario para funcionar (por ejemplo, para mantener la sesión del portal de padres). El código QR de su comprobante da acceso al estado de la visita y deja de funcionar a las 24 horas o cuando sale el último niño del registro.

## 11. Cambios a este aviso de privacidad

Este aviso puede modificarse por cambios en la ley, en nuestros servicios o en nuestras prácticas de privacidad. Las versiones nuevas se publicarán en {{url_aviso}} y estarán disponibles en la recepción de nuestras sucursales; el número de versión y la fecha de vigencia aparecen al inicio de este documento. Si un cambio implica nuevas finalidades que requieran su consentimiento, se lo pediremos de nuevo antes de usar sus datos para ellas.

## 12. Consentimiento

Al registrar la entrada de un menor, el tutor manifiesta que se le puso a disposición este aviso de privacidad y otorga su consentimiento para el tratamiento de sus datos y los del menor en los términos aquí descritos. Para las observaciones de salud del menor, que son datos sensibles, el consentimiento expreso y por escrito se recaba mediante su firma o el mecanismo de autenticación que le indique el personal de recepción.$integral$,
$simplificado$# AVISO DE PRIVACIDAD SIMPLIFICADO

{{razon_social}} («{{nombre_comercial}}»), con domicilio en {{domicilio}}, es responsable del tratamiento de sus datos personales.

¿Qué datos usamos? Del tutor: nombre, teléfono, parentesco, la persona autorizada para recoger al menor, la imagen de su identificación oficial y fotografías de llegada. De los niños y niñas: nombre, edad, fotografías de llegada y, si usted las indica, observaciones de salud como alergias, que son datos sensibles. De quien reserva un evento: nombre y teléfono. Para el programa de lealtad: su celular. Los datos de los menores se tratan con el consentimiento de quien ejerce la patria potestad o la tutela.

¿Para qué los usamos? Finalidades necesarias: controlar el acceso y la seguridad de los niños, entregarlos solo a su tutor o a la persona autorizada, cobrar los servicios, gestionar reservaciones y eventos, y cumplir obligaciones legales. Finalidades voluntarias: el programa de lealtad y el envío de promociones.

¿Cómo negarse a las finalidades voluntarias? Avise al personal de recepción al registrarse o escriba a {{correo_datos_personales}}. Negarse no afecta el servicio que contrata.

Para limitar el uso de sus datos, ejercer sus derechos de acceso, rectificación, cancelación u oposición (ARCO) o revocar su consentimiento, escriba a {{correo_datos_personales}} o llame al {{telefono_datos_personales}}.

Consulte el aviso de privacidad integral en {{url_aviso}} o pídalo en recepción.

Versión {{version}}, vigente desde el {{fecha_vigencia}}.$simplificado$
)
ON CONFLICT (version) DO NOTHING;

ALTER TABLE public.registros
    ADD COLUMN IF NOT EXISTS aviso_privacidad_version INTEGER
        REFERENCES public.avisos_privacidad(version),
    ADD COLUMN IF NOT EXISTS aviso_privacidad_aceptado_en TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS acepta_finalidades_secundarias BOOLEAN;
