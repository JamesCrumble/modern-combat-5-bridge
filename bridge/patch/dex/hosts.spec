# The Java side of the client talks to our server instead of the Gameloft hosts.
# Variables: EVE_BASE = http://127.0.0.1:18080 (plain HTTP: Java does not trust our self-signed certificate), EVE_HOST = 127.0.0.1:18080, EVE_SCHEME = http://
@class com/gameloft/android/ANMP/GloftM5HM/PushNotification/RemoteImageManager
@replace
"https://eve.gameloft.com:443/config/"
@with
"${EVE_BASE}/config/"
@count 2
@end

@class com/gameloft/android/ANMP/GloftM5HM/installer/GlotImp/b
@replace
= "etsv2.gameloft.com"
@with
= "${EVE_HOST}"
@count 1
@end

@class com/gameloft/android/ANMP/GloftM5HM/installer/GlotImp/b
@replace
const-string v3, "https://"
@with
const-string v3, "${EVE_SCHEME}"
@count 1
@end
