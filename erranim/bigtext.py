"""跳杀用的大字 —— 由 tools/make_bigtext.py 生成，请勿手改。

存的是**灰度**位图（zlib + base85），不是二值块：
  * 运行期按终端尺寸做盒式缩放，灰度映射到 ` ░▒▓█` 渐变，边缘平滑，像矢量绘制；
  * 同一份灰度还用来做立体：左上受光边缘提亮、右下边缘压暗、往右下投一层影。

重新生成：python tools/make_bigtext.py
"""

from __future__ import annotations

import base64
import zlib

# 键是分行后的短语，例如 ("FATAL ERROR", "OCCURRED")
ART: dict[tuple[str, ...], dict] = {
    ('SYSTEM', 'HALTED'): {
        "w": 200,
        "h": 80,
        "z": (
        "c-rlo;hE$h2!>OP%}|WZSd7h3jCZ$_7(h_m_>8;HO@7U0Ghcia5Yah~^MaVMl!BO3499n_=L*lS_^$=`mErnFzV3)GgzM2TQaJcO"
        "_?5oCYXASGP9BJ~5k&dbDAZp-+Y6i{bKQ=@T8^ys<;f8=h3gCH{2RFq@w;7xr5uGC5x*Vu7s+O*BO0vHAPQ?aptXsUBN-aNyS@<L"
        "P26_+3Tru%>K=vIM1sHH3Q!w`dZURMNvqNo)^ecg9;H5nwY#g8fZ%R|7%)5SC~&Vr87%eNx+C0X5jjV0UI}6VqUZ_`9yC^1$pM;s"
        "l-k=$P|Ze=MbR@3g(V!w`-a}UIiMrV{UOQ#=1^F|krb=IBsj2_N<?ZWDEr!@uz~}a8N6=hB>dxVBRlONrj(j6>{3|4fz%FOZ;h1$"
        "NK7;HyW6!x>%uOD6&#5g!r7aZgU5ILngiPF8U@J8OI->JIDkBNeZD!GX(&hAvecQur!eAZFBBXHvFK}TZVn!ZElUSInN>o$?JJKt"
        "h=W`o35V8<()1{Os0mFjh36c^L9U^p9IBGJa#EY<QFzV)wb9j87{?LPxEaxIpi|*7$5B7jkx4R{h}lTo+puKBqoKlcj+&ZOPf2Z3"
        "bU?zQrpVl~VrPcvDm;z5_b>!GEjQ*t>jiQ^jN5L7=Ny-V+%t*6!7M#}hohtLoa1O_cAKMJV9at@3JW++2e~Jbiz7fx8Bxtb(8b|b"
        "Siq5JRuS$O1vLc4362Sc1souw$Tc3Q8S)Irgu()jLrzZ@N7lMC&-jO5VFd?@tm5K`ibsMmQRp0gg%uo0R8DHVYLf`C=I#EpGFDi@"
        "0b-J^9EmT00%S9dGC14{vw4ZAYyj)EQ`}e&sui!%{NYtt!ht;LP9g>NtRE~6ufh_J#5;-1=U|s!o%6X<VF`!WvPk`X95t!6^AexJ"
        "5{`rW9?!4Du9#7Y>g87+g*6<=x=H4VAtwBK0&{XCf@;G4RN-@duFv(k{)bDC>7xv!t;B`WS@5sjvMuK+7Wh6#Hgm`~b2O9f9EY7d"
        "ZQ&p-oZ^V;IggzjHH(|#KsyWE#c?%ch9fw(72eLl(|H%iS&dXZz00v|iGH1E38Wy7(;RI3H*MtLLlh@D+AY$p9DHRs!I95#fL?j@"
        "jU4x8_!LJFyIXlX2R)PE=ScDdUD(Y*tNMNptfK(RoW6wv?%3?+01_OO?`+`+Meeu_vX?tW4CFJc<`{0-8ao-$&k>YDO#Uex$<Gm~"
        "Pbhm(dpK~K16j*+<LSSI14gpHgd^$4_u;2;jN-1m(Hyqi5_elaA8<t3%I37?R*vZ9$lX=Y51I%29HETt_jlwaX&ef6=846dCwA7?"
        "c_#;nHXe>{Y!3T4U~(Om%c$P5hXd!<wZ?fqRDYE7K8}Esb%v<dbfXIUCJu6F!d>^le&sC>Li3}%ME>aHK^+c8#rLq4!(A86mc_7N"
        "LG9v5?mD%7PJ?>-9uD;H8$|mQ1FeJY;J`SsABA=(p`QL`4!N)P2bSyzX8"
        ),
    },
    ('FATAL', 'ERROR'): {
        "w": 200,
        "h": 88,
        "z": (
        "c-rlo-I41c424sSno%({LosTGVtg|@8yoW@9f7rTAHw7M<d82Q5HkCEovj?xmS1hlpGT>EqS*X2-09s!c{Xb<j`NZ1a?G9nfFoVc"
        "Xpcj2`U4J`KXY=3HtNwFq<k?ShvpQ|k?V(PheLCU=eS8_heLDP<X}_D_isj~C9OKea)`Am!yE#xCm|eUZ3!@k=@iQGS@Pwuda*c6"
        "r%;Yln3bIv;xL^eIX<yjt|+B74%;b`qw+3Bq#GQzQy>RbKV32+UFQIt0y$DWm5oT(IRK|e_j3g|pEG=c18|Dt;9Gx2q^lf=QyfRW"
        "2c#b9DhJ{e$I<+3dZeoyh*KCxYBnrVBVFTwoWeMyUDQO2bd3XYisGQ|Z)&6~9GFwo{*n7&)FNHsz?`Build;Tb6`$E9IPE!lZOLz"
        "3gQs0_u}CIonkmhuOJZ4fjY%-WWD!{bD&N!9NyCHoC9?V;b5cldF`E6okBRoDzO)o19pnwIAfEi)px=;aHj~4d1^~m{ghUn#I>wo"
        "9K|m09~cMj6u`m9{5c!7cUpA{;K)dVUJwq4Qviqh@jQ<7F^9wHd5)x36ef{A<nTB>&r$SR?l{ti93H0?j&J+6Z~L}yQ(vc~EI%u8"
        "k<1%D1v&7KMCILaBHL`FJ0WuO31R394m_7ReiaEbD+xUB7lwc6o98CSTSJ&xX~%>Lv`>Sc+Z?zVfoF7aOc;8OqsqTgol$Bicxk0P"
        "$Z^dCR5zbg{fK~`PjDRm0#}vDmdx+jL0qq0*<I=~ujI@`luB1_LUq-x#Cp-G?kcjk?`4j9-ONtiYZCm|Y!h$aI~?7S2-W3Tjh^}e"
        "0X?@k@+6Kd-MmE4-GG3eTO0}GXmkwRbUmDXKQbQT(`BX7&=t2p&n*rx&R>(56r^nF^jzT(WZms``rQG+=Bhli?h<jehWm8-<(gz}"
        "aKpZ}?UG+1c?qj`Qd-If@)CZ9<cUeWv_&osC{M&V+<805!H?zb5Ql*0s7q&DqH}Nv_7ege_hTrg%MXpmt?vzv_hBEXGxWMAIJ&-f"
        "I2bFwv^xC`9Tw-)as<485R3VLA-XOtt-D6wEBj!w{)a`^Y3~QC<jdFh(teJbjdgo@$)xYKyd;l@7u2bFqM3W@p3eNL9HYqr>O@Jf"
        "lAU`FJy-KYwVr6`l5&nJEhFf;nzs+9DXKf{3nt?9Tt0sYSfd%~@~r5~Se-%ea)e#KQu19(N0Yh_uY0ba2h;rgVd?5O25I;nfxUef"
        "<djm>TNhePj&-+g&${TL)<q4^4G!wU4b@o}MvJ*Ibe<a=)#xUl&U$Y^_6FB_?r>ZmE<T+OQpi)2{q@}9phk%5R^F=_o?9H%3d0^<"
        "|DIssU~%`{<7h?~)m<d`duQ15Kez`#%QpW2RM66%"
        ),
    },
    ('SYSTEM', 'FAILURE'): {
        "w": 200,
        "h": 77,
        "z": (
        "c-rlo?V0Q<2!K-z%}@-@P>jt`OwP`kOrioxLNfP0&sl%%CZfJkK163(>H<_m)>Wi1EvHLP`o4l?tqa5U{PP&v>fK{cdRg64Ua#4E"
        "OHD67EmnQg{!|nOJ1s3xcY9E`m0aoDIK=pd1_!%M?XR$|FHJiG>AN`U^{~1eWVVIYn49`AmA;LG)LPISV7Dc$9IN^~m%fdoSZhb@"
        ">0tc%z<}(mEa+O2fb?w~Yrm!qj`thc#|hGWgYMsb0x%@quIggyB|1j5=CDklSY41ZN7Bs~Hm#SS^i3S3)x++BwLR+ElcphvN@qDr"
        "Bgxe>lS9CF*7Y}$ZUUy#X%4AB%ljYl^`myfi({B!|5Hv#XF0g4^!}v9<ft4ZIfIeU>H+1K0@6titXA$DfJ_c->^@tq?n=Q*9Rkux"
        "j-?WPOMuC-l-{<Z7l0YgJt95fPz73!N<p?iZ4T{{r4PPAjF2TPo#Z$aWK$1^qg@-e0ix9k5~9*Mjzd8<_3${l&uy++JNS%Br#O~<"
        ")Mb0^ar}^q*P2>BbU`}DA)luoP4PL@rcQNA?k+4Mo#No_`+d}7$nhEs%ixoWy{cl;8N0hH$VWY99Ixe54Ten(SuRPZI6ewe+NeS%"
        "xsPJ6pa6$2o#WUPWFJ6?<4}bw9FBC3gS*Jr;s7Kro$Hb?M^rk;f!$8T-~g+K66FX>=Qx(mevrFzTk{g1kEnE#L)x9X#Zhz@WcE6m"
        "q^We0gIm93agcIcXgh9`BPyNbz&4s7e_#9AJiy_ZA!4tB(x?3S)=9+yt$U?W{;Ds$L^y)dNsdE77MEj@Q9g0%KVs5Z4sO=3vyZZd"
        "qPGwZM@%})(Q2LJ&!Ge`Tz?*t&T@c}8<%O=ZS714aY;Zr%h5WeL3{<ouamLY(HP-{bG3~0Z}~01<+uDBg+qZ6cv-8W4f;x>j=+DW"
        "hVu7f1Vmg71vw}bZr#nH&Q#JI;$=F&z){6FSq}6PgkRw}K(ZX{rWe1$v5zLpv94Zz`a2xc8Z_G-SK}+w^x{1nSjC-U-l{;q`60)a"
        "Q5B=+qa25UDR*$dHW56_wmras*5#;+9G`;+G)D3?2Q+Eo97lH$ME?QD9rJ;EOYELEKgL1#=||ZOG3vSxbAU8%Aj1JwU!r`=lN^A%"
        "-G%8<A`fmQs;mU7WXX5@U|I4U^&FrY=yy0E&(RuN={5cT5$^^#+Gs>+(-%0(eE$*PXv0SAqsXT@gd_XGIR|wQ`qQ$9IpRk?6T2&;"
        "tF@2W-QxzZz%3lGuH%D^$NUFcw(~Lv&n)3-4m6?~(+{Gt1HH^4vz=y~gM1EqC`OLvDhICPvxzetXuOmW$9`$8q&bSuK^Hm14a#+V"
        "rBvi12dw@{yPV}%wBE8AJ)zG2L5{;7SEGI>IHU)m&WN)UOsKriSq>Sctk~sn+$tS+d%?Ubpoh}0tie&@fCKFmBI;Af5Qk^{%HWfB"
        "HtQNkah6H_V}mmsICe!N53|kwH4f*ZZlj)OIA*cjC|~j(#U&2=-colOe~QDXAUIJ~3jLI7#38QrsW$)TIMl5Nnwy+bRppsm{$7FC"
        "O~$`7QTWcg0)GH0>!5D"
        ),
    },
    ('FATAL', 'OCCURRED'): {
        "w": 200,
        "h": 56,
        "z": (
        "c-rln-F3qt423<6mSGr{(J(BdVcf(9^QS9tdm8f)&gnyZl~|tvA<5mg`Qi6wgjRFcXSeqwK<j89wvP;pLz)XVM{B(dM{=8{I6CWP"
        "I5=M6DUQzi0S^6Mhw}Q9R*-fh0P8h4-inasvc{oVufY+HMIwr<acI^{aKvZJ&E5qZs`U~ahfC2H9&)JGOK_wmBK=NRI8^H=<1Upx"
        "`1GXRfJ3)lfg_|3iZeZjZoL2pWf%5tr*|B{dI1hj3ne~lHaURx0{dJt)8UPn9KiZ{jy{ue1_!c!o+B9fdC!5YALk$?u_ed>tsm#`"
        "if0Ttp!MS%nxg_`X#F%t7om2`acuoG2e&5%E0wq#Tia3Z|2g!=N8af*2ey8g!*>VY={c($hV{c7(w7`uIa_fU)}Q3~j_>%6?^t1w"
        "5Aq6&5<KaW2)nW1>&TjmzbZkL;x=<a&Wy{;61eu3%CaC-{t_48^CMx7W6!ni9iihmyd_+u74DLN5=j?saKyXZ5j2injCU2d{U2=M"
        "4#$~<-4RrdD|eu@oM<D*)r`c4{@wuO%X9$=HV4;BlIMj@+kxbzeCkrIrRX8$YC28asfa1eais6x5%fqBn##D?5|pz!+WRW#_y~nr"
        "j`JIL1P~Fkv!Tsm{q<8#O|*r;XIO;7EC(TX=_W@m1^OiUx*{llhQi0^gX%)8??|!Qt}RLF4;*<B%nINR*CSPGw6todM{FnmR~+Pm"
        "9^rZcgyWXOs~oBB>$|n6?Qt_N=}w$ELFEV~hhB95FGox$ZU~rz$Mdlxj{Q#@bw)NL4CcdqaDQZHQKwX3>WnT|9ChqTQ$;8&(eL9`"
        "%q4PiHxwr0)z)UX?fFqioGJ|{c;(+tns^lxAJ_Q>1(V}?q@i6{_&k@ie4)^^X@eGCsd~9EBN!a6?sS*=RgQhGKI?tmRn~-N#p&DA"
        "p^C*Br3~OG-Z9SRyKV>hZYfAPA)Mnub$f2hrJ;a0eBo@WKi-*MTYto|igFq2Y=L9&%)iCT?FGeA!2wpOKjQJvupSJs9^{cA`b##i"
        "l$kOX`g`Dduy=}K=^lncQ@8I92jpYcZDE2#Nbh~L{gQzCB|xZqFJy)N_gvY+n1gTiuin0@{VPpyd|o#iTRAk@g3VEQ`vbxdO|J"
        ),
    },
    ('FATAL', 'FAULT'): {
        "w": 200,
        "h": 97,
        "z": (
        "c-rmT;c=rd6a-)wqh?f$no%*Y85QH)&D=R)gLW4d5Hr@#;H>!wvJq?^<=GvNh0%Ij;|WI<Bma#2e{(!mhVIC}TeHd0k37gR+0!sN"
        "`jN*t(sXmOI6&kvjzS+=+5sYuakS~?W^sVXLmYX&JsTV-@(@RzZx4e5MQV=vpvL=7rQVBQdsucx+8u@XQWG6aq}}mx+O*vcCerPA"
        "ebPtke*yCjD$?zE?O3ibnRHN*ZpZ78O}>NEJ_i+PcI3&6Lpj!EXQbH?lQXywGo5g7kzPldz0VWRbnGA_y^b>5En=o)2N}8Vx@2`q"
        "ruk)2+U_7Dt&a2-*5F=32ODX1)VH%2&vfWuBdw12pC>rep@WTdIzB%U0;MAd9qDw$$DzvLZVhzMkw!;aICarX2M#{c=vdmP3T8TR"
        "@R7#v!M5<xj%GS=@R2@8mhW{!hY;y=p!)|K973eck<d+$B0H2wo1>sNZL&j&v^g5QE0t7-66tclb71-Rdk!hm<*4{gpQ1yGbUBFk"
        "?CxvX8EJB4=Kgy~4lUB;h|Y^@XQp=?TBOI(z5Ga>nZE82BQu;xjH7=!7{o({vNO`-XxuZe&qKTJ5F;%PbYo=w3CyZPjkGw>@^yWt"
        "uR7F7i{lAaeF;A?D?1|{j)GR<zbAVm9de|@(S)^e<{WZl)~|`a<2%0NJH{ODS|4|j+k}N4*I04a`tIX^9lU!ua0l-m4&1@JhXZ%;"
        "Zs8z0c(-s69lUEDzFME#p{;0qwZ1zzm=4|z98?GI1`eu&cLN92!5iPfb@0Y_a2>qi9b^Y@cn8_RyVl{W^^NXeJ9wiz*bd(44z`0g"
        "xP$KC4ep>jcw;;G4&K-fzJoXR_aNWF8`>ds@XE*zp@T;_;wp#I!CQ~ampe9f@CI~vI(TJE(aq_QI(P}Mu&#1wwZ7FA*1}r&T!&Wc"
        "Yv`X*Ccsl2Vy!Qh?>45T2Xd!6#9H6v!!6PhBd&4CwZ7T>&wnW?2Pk}#YwJA@xz<<tojcQ^*ZLY=^gYqBq1M;kyLepV*i!4u>^~-)"
        "=-5>2%hX@vOvlDrUka)Of1YD=tuKE*yejJYjCLG5a*cmau3FTR4t%E{sOkN$"
        ),
    },
    ('KERNEL', 'PANIC'): {
        "w": 200,
        "h": 77,
        "z": (
        "c-rlo(ShV32!>M(%}|WZSPacjOm25?CQ<n@#)Qnv_;fpyK|ce6z%9J~4Oz;O*4I!f|1u*tk8eX&aw02Ht7+)}hsl%DOv6aVdmxTo"
        "A}w<qFQH^arUyA1jCqcA<yNLX$I)V3;n+Y@^OJav<ga0ZL%q$3=3rkZW;pC3<q-~m@t!~yZ`cPYY5hVHuo=wZPji9;Va#y+j5mnk"
        "(0C4rG0DO1nU|tDFvcVYRiY~8r&taL<01#}K{=Ge!?;tgQuRVYIN0j%6%JB#Ua^!<MsU!IJnkF^5od)ihN*nx0UTPKi-eas5Ojc1"
        "Kf+5c)-vb^`2<H5rryZGEyv5R<Oet$JD=fbV;kQ7MGtW3O&s?A@%xM2)T22XQ=j9|4DN%x&&Y8c`=P~`IWl~wf4|sFJ%~e`YulM~"
        "w+M8}<JguTaPGbZDA>-E{v#uhWP>e@;mGx$H17w+m%(LBpCdSOvk0B%Aa!MMH7N)9^EON^qO8+#30q^YIbOS^VfVp8y?3oRA1CIH"
        "AFOvPj$<=*xe)If&1yJy(l`!oHEV*yXjaRyXgG&CZ)WZv8OvbgT%$Os349O3S+oL$GI#+mBn?i(y&M_JQ|EeyDGr7*7&+iDj(x9a"
        "nxk<<mSb1nIF3|l)*J^_Ar9c6c#eIqc$#CMmNCbszJVN6Ua2NID$PP1i{8lb9pCXC-|-#S250#_mQ^xe6O@ix6s$vIM@FxUL68fe"
        "tW^$)Zsc&1@$lx=%1Gxp(ov@NI)}~1mwwjE)axk@8Qs4t8~{Yz*#^28EQgFM!W9mqJ!GpLRt61o$WiM4E{<MVA$ecPD97G1m53JN"
        ">=Xgca>!OH6X%8ew{k&W4RkRy9AxxpyT_zEII2|vD_266KG4O`aEM)WQ!%~Hf&GNMwoeZ#CuxL(kX7>~3rT(=1>8>G1<cjAF&f~2"
        "j`RIYzKf%|z*RMXg^wIs9^g=11o{mnm~PXn1z6m!PU<!~_PQ8qj_dAwQm^)6-&?Uz^`_IsP;oGJLw9pz>(mOXV7HRh>tYa)t<zWz"
        "bncdGSM%*a7emF7k5arh_`xI~)Tz=r*;vm&7sFE=V30Y$yp;Dq7emD%PjVz<_);Hdr@9zE#sLgJdH!mki{Vpxm4RPu0|;n7P8Y*x"
        "IF!3JpcMz<y)K5Q&fO}{K;A{rQN4jKhEMpx&P5QPXaijg6$jzCg!Dr4=a?fOHKdPpF$~3te+x+z#G&I|iRGHL!;ztZ=oRxHEdvky"
        "FN0ne!@xZ%-F=T5v+_>0IUjLsLK&E0jD1kAhrI5h?sYLV9HyB9d~z>`bJkaiG0?@(=6!OJ_xahZJxilO=M_F$wsl|*+r?n=a2k_`"
        "lLIR!=ktU)_>hA%Brhs`=ONyE63k(`7;Ju*Lh{rehiiPLr4Mv5pt?cshjn*yBuA}k7ckJp;M8&Ij^?=ds^em1xAcK7265i&$-3G<"
        "&RD%{"
        ),
    },
}

_CACHE: dict[tuple[str, ...], list[bytearray]] = {}


def get(phrase: tuple[str, ...] | str | None):
    """取短语的灰度位图：(宽, 高, [每行的 bytearray])。"""
    if phrase is None:
        return None
    if isinstance(phrase, str):
        key = tuple(phrase.split(chr(10)))
    else:
        key = tuple(phrase)
    e = ART.get(key)
    if e is None:
        return None
    rows = _CACHE.get(key)
    if rows is None:
        raw = zlib.decompress(base64.b85decode(e["z"]))
        w = e["w"]
        rows = [bytearray(raw[i * w:(i + 1) * w]) for i in range(e["h"])]
        _CACHE[key] = rows
    return e["w"], e["h"], rows


def phrases() -> list[tuple[str, ...]]:
    return list(ART)


def one_line(phrase) -> str:
    """给日志/调试用：把分行短语拼回一行。"""
    if isinstance(phrase, str):
        return phrase
    return " ".join(phrase)
