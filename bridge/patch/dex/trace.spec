# Debug build only: logs the game's installer state machine to logcat (tag mc5trace) with the call stack.
@newclass mc5/T
.class public Lmc5/T;
.super Ljava/lang/Object;

.method public static s(Ljava/lang/String;I)V
    .locals 3
    new-instance v0, Ljava/lang/StringBuilder;
    invoke-direct {v0}, Ljava/lang/StringBuilder;-><init>()V
    invoke-virtual {v0, p0}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    const-string v1, " "
    invoke-virtual {v0, v1}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    invoke-virtual {v0, p1}, Ljava/lang/StringBuilder;->append(I)Ljava/lang/StringBuilder;
    invoke-virtual {v0}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;
    move-result-object v0
    new-instance v2, Ljava/lang/Throwable;
    invoke-direct {v2}, Ljava/lang/Throwable;-><init>()V
    const-string v1, "mc5trace"
    invoke-static {v1, v0, v2}, Landroid/util/Log;->w(Ljava/lang/String;Ljava/lang/String;Ljava/lang/Throwable;)I
    return-void
.end method
@end

@class com/gameloft/android/ANMP/GloftM5HM/installer/GameInstaller
@replace
.method private o0(I)V
    .locals 11
@with
.method private o0(I)V
    .locals 13
    const-string v11, "o0"
    move/16 v12, p1
    invoke-static/range {v11 .. v12}, Lmc5/T;->s(Ljava/lang/String;I)V
@end

@class com/gameloft/android/ANMP/GloftM5HM/installer/GameInstaller
@replace
.method public m(I)V
    .locals 20
@with
.method public m(I)V
    .locals 22
    const-string v20, "m"
    move/16 v21, p1
    invoke-static/range {v20 .. v21}, Lmc5/T;->s(Ljava/lang/String;I)V
@end
