# Google Play Billing in the Gameloft IAB layer is replaced by the local store (mc5.Store in the bridge dex; documentation/protocol.md).
# The five tasks GMPUtils$a..e only call mc5.Store.run(task, bundle); s.v() accepts the marker signature MC5LOCAL.
@class com/gameloft/android/ANMP/GloftM5HM/iab/GMPUtils$a
@method a(Landroid/os/Bundle;)Ljava/lang/Integer;
.locals 1
invoke-static {p0, p1}, Lmc5/Store;->run(Ljava/lang/Object;Landroid/os/Bundle;)V
const/4 v0, 0x0
invoke-static {v0}, Ljava/lang/Integer;->valueOf(I)Ljava/lang/Integer;
move-result-object v0
return-object v0
@end

@class com/gameloft/android/ANMP/GloftM5HM/iab/GMPUtils$b
@method a(Landroid/os/Bundle;)Ljava/lang/Integer;
.locals 1
invoke-static {p0, p1}, Lmc5/Store;->run(Ljava/lang/Object;Landroid/os/Bundle;)V
const/4 v0, 0x0
invoke-static {v0}, Ljava/lang/Integer;->valueOf(I)Ljava/lang/Integer;
move-result-object v0
return-object v0
@end

@class com/gameloft/android/ANMP/GloftM5HM/iab/GMPUtils$c
@method a(Landroid/os/Bundle;)Ljava/lang/Integer;
.locals 1
invoke-static {p0, p1}, Lmc5/Store;->run(Ljava/lang/Object;Landroid/os/Bundle;)V
const/4 v0, 0x0
invoke-static {v0}, Ljava/lang/Integer;->valueOf(I)Ljava/lang/Integer;
move-result-object v0
return-object v0
@end

@class com/gameloft/android/ANMP/GloftM5HM/iab/GMPUtils$d
@method a(Landroid/os/Bundle;)Ljava/lang/Integer;
.locals 1
invoke-static {p0, p1}, Lmc5/Store;->run(Ljava/lang/Object;Landroid/os/Bundle;)V
const/4 v0, 0x0
invoke-static {v0}, Ljava/lang/Integer;->valueOf(I)Ljava/lang/Integer;
move-result-object v0
return-object v0
@end

@class com/gameloft/android/ANMP/GloftM5HM/iab/GMPUtils$e
@method a(Landroid/os/Bundle;)Ljava/lang/Integer;
.locals 1
invoke-static {p0, p1}, Lmc5/Store;->run(Ljava/lang/Object;Landroid/os/Bundle;)V
const/4 v0, 0x0
invoke-static {v0}, Ljava/lang/Integer;->valueOf(I)Ljava/lang/Integer;
move-result-object v0
return-object v0
@end

@class com/gameloft/android/ANMP/GloftM5HM/iab/s
@insert-after
.method public static v(Ljava/security/PublicKey;Ljava/lang/String;Ljava/lang/String;)Z
    .locals 3
@with
    const-string v0, "MC5LOCAL"
    invoke-virtual {v0, p2}, Ljava/lang/String;->equals(Ljava/lang/Object;)Z
    move-result v0
    if-eqz v0, :mc5_real
    const/4 v0, 0x1
    return v0
    :mc5_real
@end
